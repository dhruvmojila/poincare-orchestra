"""Provider-agnostic ensemble (paper §IV-D): providers, throttling detection, load balancing, failover."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict, deque
from typing import Any, Protocol, runtime_checkable

import numpy as np

from .profiles import CapabilityProfile
from .schema import AgentResponse, Claim, CompletionRequest, ThrottleEvent

logger = logging.getLogger("poincare_orchestra")


@runtime_checkable
class Provider(Protocol):
    """Anything with a ``name`` and a ``complete(request) -> AgentResponse`` method."""

    name: str

    def complete(self, request: CompletionRequest) -> AgentResponse: ...


def _tokens(text: str) -> int:
    return max(1, len(re.findall(r"\w+|[^\w\s]", text)))


def information_density(text: str) -> float:
    """Unique-token ratio: a cheap proxy for the paper's bits-per-token notion."""
    toks = re.findall(r"\w+", text.lower())
    return len(set(toks)) / len(toks) if toks else 0.0


def looks_like_refusal(text: str) -> bool:
    """Short replies of the form "I cannot/can't/am unable to help|assist|comply"."""
    return (
        bool(re.search(r"\b(cannot|can't|unable to) (help|assist|comply)\b", text, re.I)) and len(text) < 200
    )


def parse_completion(text: str) -> tuple[str, list[Claim]]:
    """Split a model reply into ``(answer, claims)``.

    The reply is expected to contain a JSON object ``{"answer": str, "claims": [...]}``
    (code fences and surrounding prose are tolerated); otherwise the whole text is the
    answer and there are no claims. Malformed claim entries are skipped.
    """
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return text, []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return text, []
    if not isinstance(data, dict):
        return text, []
    answer = str(data.get("answer", text))
    claims: list[Claim] = []
    raw = data.get("claims", [])
    if isinstance(raw, list):
        for c in raw:
            if isinstance(c, dict) and c.get("text"):
                try:
                    claims.append(Claim.model_validate(c))
                except ValueError:
                    logger.debug("skipping malformed claim %r", c)
    return answer, claims


class MockProvider:
    """Deterministic provider that answers from the retrieved context.

    It lets the whole orchestration run offline and in tests. ``degrade_after``
    simulates a throttled commercial model: after that many calls, answers
    become truncated, slow and sometimes refused, which the detector should
    catch and the router should route around. ``fail_after`` simulates an
    outage: after that many calls every call raises ``RuntimeError``.
    """

    def __init__(
        self,
        name: str,
        degrade_after: int | None = None,
        latency_s: float = 0.01,
        seed: int = 0,
        fail_after: int | None = None,
    ) -> None:
        self.name = name
        self.degrade_after = degrade_after
        self.fail_after = fail_after
        self.latency_s = latency_s
        self.calls = 0
        self.rng = np.random.default_rng(seed)

    def complete(self, request: CompletionRequest) -> AgentResponse:
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise RuntimeError(f"{self.name}: simulated outage on call {self.calls}")
        degraded = self.degrade_after is not None and self.calls > self.degrade_after
        t0 = time.perf_counter()
        time.sleep(self.latency_s * (6 if degraded else 1))
        n_ctx = max(1, min(len(request.context), int(3 + 2 * request.budget)))
        claims = [
            Claim(text=c, confidence=float(np.clip(0.95 - 0.07 * rank, 0.3, 1.0)), sources=[cid])
            for rank, (c, cid) in enumerate(
                zip(request.context[:n_ctx], request.context_ids[:n_ctx], strict=False)
            )
        ]
        bullets = "\n".join(f"- {c.text}" for c in claims)
        content = f"[{request.role_name}] On '{request.subtask.question}':\n{bullets}\nAssessment: {len(claims)} relevant records support this answer."
        refused = False
        if degraded:
            if self.rng.random() < 0.4:
                content = "I am unable to help with this request."
                refused = True
                claims = []
            else:
                content = content[: max(20, len(content) // 5)]
                claims = claims[:1]
        latency = time.perf_counter() - t0
        return AgentResponse(
            subtask_id=request.subtask.id,
            role=request.role_name,
            provider=self.name,
            content=content,
            claims=claims,
            confidence=float(np.mean([c.confidence for c in claims])) if claims else 0.0,
            sources=[s for c in claims for s in c.sources],
            latency_s=latency,
            tokens=_tokens(content),
            refused=refused,
        )


class LiteLLMProvider:
    """Any model LiteLLM can reach (``pip install 'poincare-orchestra[litellm]'``).

    ``model`` is a LiteLLM model string such as ``openai/gpt-4o-mini``,
    ``anthropic/claude-haiku-5-5`` or ``ollama/llama3``; credentials come
    from the environment variables LiteLLM reads for that provider. The prompt
    asks for a JSON object ``{"answer": str, "claims": [{"text", "confidence",
    "sources"}]}``; plain text is accepted as a fallback. ``timeout_s`` is passed
    to ``litellm.completion(timeout=...)``; a timeout raises and the router
    treats it like any other provider error (refused response, throttle event,
    failover). Extra keyword arguments go to ``litellm.completion`` unchanged.
    """

    def __init__(
        self,
        name: str,
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 600,
        timeout_s: float | None = None,
        **kwargs: Any,
    ) -> None:
        try:
            import litellm  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "LiteLLMProvider needs litellm: pip install 'poincare-orchestra[litellm]'"
            ) from exc
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        self.name = name
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_s = timeout_s
        self.kwargs = kwargs

    def build_messages(self, request: CompletionRequest) -> list[dict[str, str]]:
        """The system and user messages sent for a request."""
        ctx = "\n".join(f"[{cid}] {c}" for cid, c in zip(request.context_ids, request.context, strict=False))
        user = (
            f"Context records:\n{ctx}\n\nTask: {request.subtask.question}\n\n"
            'Reply as JSON: {"answer": "...", "claims": [{"text": "...", "confidence": 0.0-1.0, "sources": ["record id"]}]}'
        )
        return [
            {"role": "system", "content": request.system_prompt},
            {"role": "user", "content": user},
        ]

    def complete(self, request: CompletionRequest) -> AgentResponse:
        import litellm

        params: dict[str, Any] = dict(self.kwargs)
        if self.timeout_s is not None:
            params["timeout"] = self.timeout_s
        t0 = time.perf_counter()
        resp = litellm.completion(
            model=self.model,
            messages=self.build_messages(request),
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            **params,
        )
        latency = time.perf_counter() - t0
        text = resp.choices[0].message.content or ""
        answer, claims = parse_completion(text)
        usage = getattr(resp, "usage", None)
        tokens = int(getattr(usage, "completion_tokens", 0) or _tokens(text))
        logger.debug(
            "%s (%s) answered %s in %.2fs, %d tokens, %d claims",
            self.name,
            self.model,
            request.subtask.id,
            latency,
            tokens,
            len(claims),
        )
        return AgentResponse(
            subtask_id=request.subtask.id,
            role=request.role_name,
            provider=self.name,
            content=answer,
            claims=claims,
            confidence=float(np.mean([c.confidence for c in claims])) if claims else 0.5,
            sources=[s for c in claims for s in c.sources],
            latency_s=latency,
            tokens=tokens,
            refused=looks_like_refusal(text),
        )


class ThrottleDetector:
    """Flags responses whose latency, length, density or refusal pattern breaks the provider's baseline.

    The baseline is the provider's own recent responses (the last ``window``
    that were not flagged); while a provider has fewer than ``min_history`` of
    them, the pooled responses of all providers stand in for it. A response is
    flagged when it is refused, when its latency exceeds ``latency_factor``
    times the baseline median, when its token count is below ``length_ratio``
    times the baseline median, or when its information density is more than
    ``density_drop`` below the baseline median. Flagged responses do not enter
    the baseline.
    """

    def __init__(
        self,
        window: int = 6,
        min_history: int = 2,
        latency_factor: float = 3.0,
        length_ratio: float = 0.4,
        density_drop: float = 0.35,
    ) -> None:
        self.window = window
        self.min_history = min_history
        self.latency_factor = latency_factor
        self.length_ratio = length_ratio
        self.density_drop = density_drop
        self.history: dict[str, deque[tuple[float, int, float]]] = defaultdict(lambda: deque(maxlen=window))

    def observe(self, response: AgentResponse) -> ThrottleEvent | None:
        """Record a response; return a :class:`ThrottleEvent` if it breaks the baseline, else ``None``."""
        hist = self.history[response.provider]
        density = information_density(response.content)
        reasons: list[str] = []
        if response.refused:
            reasons.append("refusal")
        # baseline: the provider's own recent behaviour, or every provider's while its history is short
        baseline = (
            list(hist) if len(hist) >= self.min_history else [h for hs in self.history.values() for h in hs]
        )
        if len(baseline) >= self.min_history:
            lat = np.array([h[0] for h in baseline])
            toks = np.array([h[1] for h in baseline])
            dens = np.array([h[2] for h in baseline])
            if response.latency_s > self.latency_factor * max(float(np.median(lat)), 1e-3):
                reasons.append(f"latency {response.latency_s:.2f}s vs median {np.median(lat):.2f}s")
            if response.tokens < self.length_ratio * float(np.median(toks)):
                reasons.append(f"length {response.tokens} vs median {int(np.median(toks))}")
            if density < float(np.median(dens)) - self.density_drop:
                reasons.append(f"density {density:.2f} vs median {np.median(dens):.2f}")
        if not reasons:
            hist.append((response.latency_s, response.tokens, density))
            return None
        return ThrottleEvent(
            provider=response.provider,
            reasons=reasons,
            latency_s=response.latency_s,
            tokens=response.tokens,
            density=density,
        )


class Router:
    """Chooses a provider for each role by capability profile and health; fails over on throttling.

    Candidates are ordered by: the profile's preferred provider first, then
    providers that are not cooling down, then the least loaded. A flagged
    response or a provider exception puts the provider in cooldown: it is
    skipped for the next ``cooldown_calls`` calls and the next candidate is
    tried; the last response is returned if every candidate fails. When every provider is
    cooling down they are tried anyway, least-degraded first, so a call never
    fails only because of cooldowns. ``call`` never raises on a provider
    exception: it is converted into a refused :class:`AgentResponse` and a
    :class:`ThrottleEvent` with reason ``error: <exception type>``.
    """

    def __init__(
        self,
        providers: list[Provider],
        profiles: list[CapabilityProfile],
        detector: ThrottleDetector | None = None,
        cooldown_calls: int = 3,
    ) -> None:
        if not providers:
            raise ValueError("at least one provider is required")
        names = [p.name for p in providers]
        if len(set(names)) != len(names):
            raise ValueError(f"provider names must be unique, got {names}")
        self.providers = {p.name: p for p in providers}
        self.profiles = {p.name: p for p in profiles}
        self.detector = detector or ThrottleDetector()
        self.cooldown_calls = cooldown_calls
        self.degraded: dict[str, int] = {}
        self.load: dict[str, int] = defaultdict(int)
        self.events: list[ThrottleEvent] = []

    def _candidates(self, profile_name: str) -> list[str]:
        preferred = self.profiles[profile_name].provider if profile_name in self.profiles else None
        names = list(self.providers)
        names.sort(key=lambda n: (n != preferred, self.degraded.get(n, 0) > 0, self.load[n]))
        return names

    def tick(self) -> None:
        """Advance every cooldown by one call (called automatically at the end of each :meth:`call`)."""
        self._tick(set())

    def _tick(self, exclude: set[str]) -> None:
        for n in list(self.degraded):
            if n in exclude:
                continue
            self.degraded[n] -= 1
            if self.degraded[n] <= 0:
                del self.degraded[n]

    @staticmethod
    def _error_response(
        request: CompletionRequest, provider: str, exc: Exception, latency: float
    ) -> AgentResponse:
        return AgentResponse(
            subtask_id=request.subtask.id,
            role=request.role_name,
            provider=provider,
            content=f"provider error: {type(exc).__name__}: {exc}",
            confidence=0.0,
            latency_s=latency,
            tokens=0,
            refused=True,
            meta={"error": f"{type(exc).__name__}: {exc}"},
        )

    def call(self, request: CompletionRequest, profile_name: str) -> AgentResponse:
        """Complete ``request`` with the best healthy provider for ``profile_name`` (see the class docstring)."""
        names = self._candidates(profile_name)
        available = [n for n in names if self.degraded.get(n, 0) <= 0]
        if not available:  # every provider is cooling down: try them anyway, least degraded first
            available = sorted(names, key=lambda n: self.degraded[n])
            logger.info("all providers are cooling down; trying %s anyway", available)
        flagged_now: set[str] = set()
        last: AgentResponse | None = None
        for name in available:
            self.load[name] += 1
            t0 = time.perf_counter()
            try:
                resp = self.providers[name].complete(request)
            except Exception as exc:
                latency = time.perf_counter() - t0
                resp = self._error_response(request, name, exc, latency)
                event: ThrottleEvent | None = ThrottleEvent(
                    provider=name,
                    reasons=[f"error: {type(exc).__name__}"],
                    latency_s=latency,
                    tokens=0,
                    density=0.0,
                )
                logger.warning(
                    "provider %s raised %s on %s: %s", name, type(exc).__name__, request.subtask.id, exc
                )
            else:
                event = self.detector.observe(resp)
            if event is None:
                logger.debug(
                    "%s answered %s via %s (%.3fs, %d tokens, refused=%s)",
                    request.role_name,
                    request.subtask.id,
                    name,
                    resp.latency_s,
                    resp.tokens,
                    resp.refused,
                )
                self._tick(flagged_now)
                return resp
            self.events.append(event)
            self.degraded[name] = self.cooldown_calls
            flagged_now.add(name)
            resp.meta["throttle"] = event.reasons
            logger.info(
                "throttling on %s (%s); cooling down for %d calls",
                name,
                "; ".join(event.reasons),
                self.cooldown_calls,
            )
            last = resp
        assert last is not None  # `available` is never empty
        logger.warning(
            "every provider failed for %s; returning the last response from %s",
            request.subtask.id,
            last.provider,
        )
        self._tick(flagged_now)
        return last
