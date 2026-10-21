# Ensemble

The provider-agnostic ensemble (paper §IV-D) executes sub-tasks: capability-profiled providers, a throttling detector that compares every response with the provider's own baseline, and a router that balances load, applies cooldowns and fails over.

## Providers

A provider is anything with a `name` and a method `complete(request: CompletionRequest) -> AgentResponse` (the `Provider` protocol). The request carries the sub-task, the role name and system prompt, the retrieved context (texts, record ids and time weights) and the budget. The response is the paper's standardised schema: `content`, `claims` (text, confidence, source record ids), `confidence`, `sources`, `latency_s`, `tokens`, `refused` and a free `meta` dict.

### MockProvider

`MockProvider(name, degrade_after=None, latency_s=0.01, seed=0, fail_after=None)` answers deterministically from the context: it turns the first `min(len(context), 3 + 2 · budget)` records into claims with confidence `0.95 − 0.07 · rank` and writes a bullet list. It is the default provider everywhere and what the test suite and the bundled evaluation use.

- `degrade_after=N`: after `N` calls the provider behaves like a throttled commercial model — six times the latency and, with probability 0.4 (seeded), a refusal, otherwise an answer cut to a fifth with a single claim.
- `fail_after=N`: after `N` calls every call raises `RuntimeError`, simulating an outage.

On the command line these are `--degrade-after` and `--fail-after`, applied to the alphabetically first provider.

### LiteLLMProvider

`LiteLLMProvider(name, model, temperature=0.2, max_tokens=600, timeout_s=None, **kwargs)` reaches any model LiteLLM supports (`pip install 'poincare-orchestra[litellm]'`). The prompt sends the context records with their ids and asks for a JSON object `{"answer": ..., "claims": [{"text", "confidence", "sources"}]}`; `parse_completion` extracts it from the reply (code fences and surrounding prose are tolerated, malformed claims are skipped) and falls back to plain text with no claims. Short replies of the form "I cannot/can't/am unable to help|assist|comply" are marked `refused`. Token counts come from the provider's usage report when present.

`timeout_s` is passed to `litellm.completion(timeout=...)`; a timeout raises inside the provider and the router handles it like any other exception (below). Extra keyword arguments (`api_base`, `api_key`, …) go to `litellm.completion` unchanged.

Credentials and model names follow LiteLLM's conventions:

| Provider | Credentials | Example model string |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | `openai/gpt-4o-mini` |
| Anthropic | `ANTHROPIC_API_KEY` | `anthropic/claude-haiku-5-5` |
| Ollama (local) | none; the server listens on `http://localhost:11434` by default, override with `api_base=` or `OLLAMA_API_BASE` | `ollama/llama3` |

Model ids change over time; the current list is in LiteLLM's provider documentation.

<!-- no-exec -->
```python
from poincare_orchestra import LiteLLMProvider, Orchestrator, load_scenario

scenario = load_scenario("support_kb")
providers = [
    LiteLLMProvider("provider-a", "openai/gpt-4o-mini", timeout_s=60),
    LiteLLMProvider("provider-b", "ollama/llama3", api_base="http://localhost:11434"),
]
print(Orchestrator(scenario, providers=providers).run("What is the current API rate limit?").explain())
```

Provider names should match the `provider` field of the scenario's capability profiles (`provider-a`, `provider-b` in the bundled scenarios); the router prefers the profile's provider and load-balances across the others. If a profile names a provider that was not given, a warning is logged and its roles are routed to whatever is available.

## Capability profiles

A `CapabilityProfile` describes a model statically: `domains`, `reasoning`, `creativity`, `reliability`, `cost_per_call`, `latency_s` and the `provider` it runs on. The controller uses profiles twice — to match roles to sub-tasks and to price them ([Controller](controller.md#capability-matching)) — and the router uses `provider` as the preferred route for each role. The dynamic performance characteristics the paper mentions are the detector's and router's state: recent latencies, lengths, densities, refusals and cooldowns.

## Throttling detector

`ThrottleDetector.observe(response)` returns a `ThrottleEvent` when a response breaks the provider's baseline, or `None` and adds the response to the baseline. The baseline is the provider's own last `window` unflagged responses; while a provider has fewer than `min_history` of them, the pooled unflagged responses of all providers stand in, so detection works from the second call of a run.

| Signal | Fires when | Default threshold |
|---|---|---|
| `refusal` | the response is marked `refused` | — |
| `latency` | `latency_s` exceeds `latency_factor` × the baseline median latency | `latency_factor=3.0` |
| `length` | `tokens` is below `length_ratio` × the baseline median token count | `length_ratio=0.4` |
| `density` | the unique-token ratio of the content is more than `density_drop` below the baseline median | `density_drop=0.35` |

Defaults: `window=6`, `min_history=2`. Flagged responses never enter the baseline, so one bad answer does not lower the bar for the next.

```python
from poincare_orchestra import AgentResponse, ThrottleDetector

detector = ThrottleDetector()


def response(content: str, latency_s: float, refused: bool = False) -> AgentResponse:
    return AgentResponse(
        subtask_id="q1",
        role="tier2",
        provider="provider-a",
        content=content,
        latency_s=latency_s,
        tokens=len(content.split()),
        refused=refused,
    )


normal = "The API rate limit is 250 requests per second per project since release 2.4, with bursts up to 500 for 10 seconds."
for _ in range(3):
    print(detector.observe(response(normal, 0.8)))  # builds the baseline
print(detector.observe(response(normal, 3.0)))  # slow
print(detector.observe(response("Rate limit: 250.", 0.8)))  # short
print(detector.observe(response("limit " * 20, 0.8)))  # repetitive
print(detector.observe(response("I am unable to help with this request.", 0.8, refused=True)))
print(detector.observe(response(normal, 0.9)))  # back to normal
```

```text
None
None
None
provider='provider-a' reasons=['latency 3.00s vs median 0.80s'] latency_s=3.0 tokens=22 density=0.9565217391304348
provider='provider-a' reasons=['length 3 vs median 22'] latency_s=0.8 tokens=3 density=1.0
provider='provider-a' reasons=['density 0.05 vs median 0.96'] latency_s=0.8 tokens=20 density=0.05
provider='provider-a' reasons=['refusal', 'length 8 vs median 22'] latency_s=0.8 tokens=8 density=1.0
None
```

## Router

`Router(providers, profiles, detector=None, cooldown_calls=3)` chooses a provider per call:

1. **Candidate order**: the profile's preferred provider first, then providers that are not cooling down, then the least loaded (`load` counts attempted calls).
2. **Detection**: every response goes through the detector. An unflagged response is returned.
3. **Cooldown and failover**: a flagged response puts the provider in cooldown — it is skipped for the next `cooldown_calls` router calls — and the next candidate is tried. If every candidate is flagged, the last response is returned (never an exception).
4. **Provider exceptions**: if `complete()` raises, the router catches the exception, builds a refused `AgentResponse` whose content is `provider error: <Type>: <message>` (the error is also in `meta["error"]`), records a `ThrottleEvent` with reason `error: <Type>`, puts the provider in cooldown and fails over exactly as for a flagged response. `Orchestrator.run` therefore never raises because of a provider.
5. **All providers cooling down**: they are tried anyway, least-degraded first, so a call is never refused merely because of cooldowns.

`router.events` lists every throttle event, `router.degraded` the remaining cooldown per provider, and each flagged response carries `meta["throttle"]` with the reasons.

```python
from poincare_orchestra import CapabilityProfile, CompletionRequest, MockProvider, Router, SubTask

request = CompletionRequest(
    subtask=SubTask(id="q1", question="What is the current API rate limit?"),
    role_name="tier2",
    system_prompt="You are tier-2 support.",
    context=["API rate limit is 250 requests per second per project since release 2.4"],
    context_ids=["rate_new"],
    budget=1.0,
)
router = Router(
    [MockProvider("provider-a", fail_after=0, latency_s=0.0), MockProvider("provider-b", latency_s=0.0)],
    [CapabilityProfile(name="tier2-model", provider="provider-a")],
)
for _ in range(5):
    answer = router.call(request, "tier2-model")
    print(answer.provider, answer.refused, dict(router.degraded))
print([event.reasons for event in router.events])
```

```text
provider-b False {'provider-a': 3}
provider-b False {'provider-a': 2}
provider-b False {'provider-a': 1}
provider-b False {}
provider-b False {'provider-a': 3}
[['error: RuntimeError'], ['error: RuntimeError']]
```

The failing `provider-a` is tried on the first call, skipped for three calls, retried on the fifth call, fails again and cools down again; every call is answered by `provider-b`.

### Throttling inside a run

`--degrade-after 1` makes `provider-a` degrade from its second call. In this four-sub-task question `q1` and `q4` both prefer `provider-a`; the baseline after two responses (one per provider) is enough for the detector to flag `q4`'s truncated, slow reply on two signals, and the router fails over to `provider-b`:

```bash
poincare-orchestra run sprint_coaching "Athlete A shows forward trunk lean at the end of the race; explain the injury implication and then recommend a drill." --degrade-after 1
```

```text
Question: Athlete A shows forward trunk lean at the end of the race; explain the injury implication and then recommend a drill.
Intent: planning  complexity=1.00  domains=['biomechanics', 'physiology', 'athletes']  entities=['athlete_a', 'a_better']
  [q1] role=biomechanist gain=0.32 cost=3.00 budget=1.89  ... (focus: biomechanics)
  [q2] role=physiologist gain=0.31 cost=3.00 budget=0.00 SKIPPED (budget)  ... (focus: physiology)
  [q3] role=strength_coach gain=0.32 cost=1.20 budget=4.00  ... (focus: athletes)
  [q4] role=physiologist gain=0.36 cost=3.00 budget=2.11  Athlete A shows forward trunk lean at the end of the race
  <- q1 via provider-a (0.01s, 155 tok, conf 0.77)
  <- q3 via provider-b (0.01s, 183 tok, conf 0.64)
  <- q4 via provider-b (0.01s, 156 tok, conf 0.74)
  !! throttling on provider-a: latency 0.06s vs median 0.01s, length 36 vs median 169
Scores: coverage=0.75, density=1.00, agreement=0.17, recency=0.88, cost=0.10  J=0.663  constraints_met=True uncertainty=0.27 refinements=0
Answer:
Synthesis across 3 perspective(s): biomechanist, physiologist, strength_coach.
  ...
```

(The sub-task questions are abbreviated with `...` here; the full question text is printed on each line. The latency figures depend on the machine.) A degradation on the *first* call of a run cannot be detected by comparison — there is no baseline yet — which is why `--degrade-after 0` on a three-sub-task question may pass unflagged unless the mock refuses outright. Over several runs on the same `Orchestrator` the baseline persists and later degradations are caught.

### An outage inside a run

```bash
poincare-orchestra run support_kb "What is the current API rate limit?" --fail-after 0
```

```text
WARNING provider provider-a raised RuntimeError on q1: provider-a: simulated outage on call 1
Question: What is the current API rate limit?
Intent: factual  complexity=0.70  domains=['api', 'storage', 'tickets', 'releases']  entities=[]
  [q1] role=tier2 gain=0.31 cost=2.04 budget=1.40  What is the current API rate limit? (focus: api)
  [q2] role=tier2 gain=0.31 cost=2.04 budget=1.41  What is the current API rate limit? (focus: storage)
  [q3] role=tier1 gain=0.31 cost=0.68 budget=3.20  What is the current API rate limit? (focus: tickets)
  <- q1 via provider-b (0.01s, 122 tok, conf 0.81)
  <- q2 via provider-b (0.01s, 92 tok, conf 0.84)
  <- q3 via provider-b (0.01s, 160 tok, conf 0.70)
  !! throttling on provider-a: error: RuntimeError
Scores: coverage=1.00, density=1.00, agreement=0.31, recency=0.95, cost=0.21  J=0.805  constraints_met=True uncertainty=0.15 refinements=0
Answer:
  ...
```

The WARNING line is the library's log (always shown by the CLI); the `!!` line is the event in the result. `q2` goes straight to `provider-b` because `provider-a` is cooling down, and the answer is complete.
