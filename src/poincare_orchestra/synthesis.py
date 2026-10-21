"""Response synthesis (paper §III-D, §IV-E): fusion, multi-objective scoring with epsilon constraints,
uncertainty from agreement, and iterative refinement."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from poincare_memory import HashingEmbedder

from .schema import AgentResponse, Claim, Plan, SynthesisResult

_EMB = HashingEmbedder(dim=128)


def fuse_claims(responses: list[AgentResponse], merge_threshold: float = 0.85) -> list[Claim]:
    """Merge near-duplicate claims across sources; confidence is the max, sources are pooled."""
    claims = [c for r in responses if not r.refused for c in r.claims]
    if not claims:
        return []
    E = _EMB.embed([c.text for c in claims])
    merged: list[Claim] = []
    merged_vecs: list[np.ndarray] = []
    for c, e in zip(claims, E, strict=True):
        hit = None
        for i, v in enumerate(merged_vecs):
            if float(e @ v) >= merge_threshold:
                hit = i
                break
        if hit is None:
            merged.append(Claim(text=c.text, confidence=c.confidence, sources=list(c.sources)))
            merged_vecs.append(e)
        else:
            m = merged[hit]
            m.confidence = max(m.confidence, c.confidence)
            m.sources = sorted(set(m.sources) | set(c.sources))
    merged.sort(key=lambda c: (-c.confidence, c.text))
    return merged


def agreement(responses: list[AgentResponse]) -> float:
    """Mean pairwise overlap of claim sources across distinct providers (1 = every provider agrees)."""
    sets = [set(r.sources) for r in responses if not r.refused and r.sources]
    if len(sets) < 2:
        return 1.0 if sets else 0.0
    vals = []
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            vals.append(len(sets[i] & sets[j]) / len(sets[i] | sets[j]))
    return float(np.mean(vals))


@dataclass
class Objectives:
    coverage: float
    density: float
    agreement: float
    recency: float
    cost: float

    def as_dict(self) -> dict[str, float]:
        return {
            "coverage": self.coverage,
            "density": self.density,
            "agreement": self.agreement,
            "recency": self.recency,
            "cost": self.cost,
        }


def score_objectives(
    plan: Plan,
    responses: list[AgentResponse],
    claims: list[Claim],
    recency_weights: dict[str, float],
    spent: float,
    budget: float,
) -> Objectives:
    answered = {r.subtask_id for r in responses if not r.refused and r.claims}
    coverage = len(answered) / max(1, len(plan.subtasks))
    toks = sum(r.tokens for r in responses if not r.refused)
    density = min(1.0, len(claims) / max(1.0, toks / 60.0)) if toks else 0.0
    agr = agreement(responses)
    cited = [recency_weights.get(s, 0.0) for c in claims for s in c.sources]
    recency = float(np.mean(cited)) if cited else 0.0
    cost = float(np.clip(1.0 - spent / max(budget, 1e-6), 0.0, 1.0))
    return Objectives(coverage, density, agr, recency, cost)


def weighted_sum(
    obj: dict[str, float], weights: dict[str, float], constraints: dict[str, float]
) -> tuple[float, bool, list[str]]:
    """Paper eq. 7: maximise Σ w_i f_i subject to f_j ≥ ε_j."""
    total_w = sum(weights.values()) or 1.0
    j = sum(weights.get(k, 0.0) * v for k, v in obj.items()) / total_w
    violated = [k for k, eps in constraints.items() if obj.get(k, 0.0) < eps]
    return j, not violated, violated


def _uncertainty(responses: list[AgentResponse], claims: list[Claim]) -> float:
    """Proxy: low claim confidence and refusals raise it; cross-provider disagreement is reported separately."""
    if not claims:
        return 1.0
    conf = float(np.mean([c.confidence for c in claims]))
    refusal_rate = sum(r.refused for r in responses) / max(1, len(responses))
    return float(np.clip(1.0 - conf * (1.0 - refusal_rate), 0.0, 1.0))


def compose_answer(plan: Plan, claims: list[Claim], responses: list[AgentResponse]) -> str:
    roles = sorted({r.role for r in responses if not r.refused})
    lines = [
        f"Synthesis across {len(roles)} perspective(s): {', '.join(roles)}."
        if roles
        else "No usable responses."
    ]
    for c in claims:
        src = f" [{', '.join(c.sources)}]" if c.sources else ""
        lines.append(f"- ({c.confidence:.2f}) {c.text}{src}")
    unanswered = [
        st.question
        for st in plan.subtasks
        if st.id not in {r.subtask_id for r in responses if not r.refused and r.claims}
    ]
    if unanswered:
        lines.append("Open sub-questions: " + "; ".join(unanswered))
    return "\n".join(lines)


def synthesize(
    plan: Plan,
    responses: list[AgentResponse],
    recency_weights: dict[str, float],
    weights: dict[str, float],
    constraints: dict[str, float],
    spent: float,
    budget: float,
    refinements: int = 0,
) -> SynthesisResult:
    claims = fuse_claims(responses)
    obj = score_objectives(plan, responses, claims, recency_weights, spent, budget)
    j, ok, violated = weighted_sum(obj.as_dict(), weights, constraints)
    return SynthesisResult(
        answer=compose_answer(plan, claims, responses),
        claims=claims,
        objective_scores=obj.as_dict(),
        weighted_score=j,
        constraints_met=ok,
        violated=violated,
        uncertainty=_uncertainty(responses, claims),
        refinements=refinements,
    )
