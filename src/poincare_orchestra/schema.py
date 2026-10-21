"""Standardised schemas shared by every component (paper §IV-D "response standardization")."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SubTask(BaseModel):
    """One unit of the decomposition (eq. 5) with its role, dependencies, gain, cost and budget."""

    id: str
    question: str
    role: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    branch_id: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    query_text: str | None = None
    """Text used for retrieval; the question itself may carry a display-only focus label."""
    expected_gain: float = 0.0
    cost: float = 1.0
    budget: float = 0.0
    skipped: bool = False


class Plan(BaseModel):
    """Output of the controller: query analysis plus the ordered sub-tasks."""

    query: str
    intent: str
    complexity: float
    domains: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    subtasks: list[SubTask] = Field(default_factory=list)


class Claim(BaseModel):
    """An atomic statement with confidence and the memory record ids that support it."""

    text: str
    confidence: float = 0.5
    sources: list[str] = Field(default_factory=list)


class CompletionRequest(BaseModel):
    """What a provider receives: the sub-task, the role's system prompt and the retrieved context."""

    subtask: SubTask
    role_name: str
    system_prompt: str
    context: list[str] = Field(default_factory=list)
    context_ids: list[str] = Field(default_factory=list)
    context_weights: list[float] = Field(default_factory=list)
    budget: float = 1.0


class AgentResponse(BaseModel):
    """Standardised provider output (paper §IV-D): content, claims, confidence, cost signals, refusal flag."""

    subtask_id: str
    role: str
    provider: str
    content: str
    claims: list[Claim] = Field(default_factory=list)
    confidence: float = 0.5
    sources: list[str] = Field(default_factory=list)
    latency_s: float = 0.0
    tokens: int = 0
    refused: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)


class ThrottleEvent(BaseModel):
    """A response that broke its provider's baseline, or a provider exception (reason ``error: <type>``)."""

    provider: str
    reasons: list[str]
    latency_s: float
    tokens: int
    density: float


class SynthesisResult(BaseModel):
    """Fused answer with the five objective scores, eq. 7 weighted sum, constraint status and uncertainty."""

    answer: str
    claims: list[Claim]
    objective_scores: dict[str, float]
    weighted_score: float
    constraints_met: bool
    violated: list[str] = Field(default_factory=list)
    uncertainty: float
    refinements: int = 0


class RunResult(BaseModel):
    """Everything one :meth:`~poincare_orchestra.Orchestrator.run` produced."""

    question: str
    plan: Plan
    responses: list[AgentResponse]
    synthesis: SynthesisResult
    allocations: dict[str, float]
    throttle_events: list[ThrottleEvent] = Field(default_factory=list)
    trace: list[str] = Field(default_factory=list)

    def to_json(self, indent: int | None = 2) -> str:
        """The whole result (plan, responses, synthesis, allocations, events, trace) as JSON text."""
        return self.model_dump_json(indent=indent)

    @classmethod
    def from_json(cls, text: str) -> RunResult:
        """Inverse of :meth:`to_json`."""
        return cls.model_validate_json(text)

    def explain(self) -> str:
        """Human-readable trace: question, plan, responses, throttle events, scores and the answer."""
        lines = [
            f"Question: {self.question}",
            f"Intent: {self.plan.intent}  complexity={self.plan.complexity:.2f}  domains={self.plan.domains}  entities={self.plan.entities}",
        ]
        for st in self.plan.subtasks:
            dep = f" after {st.depends_on}" if st.depends_on else ""
            if st.skipped:
                dep += " SKIPPED (budget)"
            lines.append(
                f"  [{st.id}] role={st.role} gain={st.expected_gain:.2f} cost={st.cost:.2f} budget={st.budget:.2f}{dep}  {st.question}"
            )
        for r in self.responses:
            flag = " REFUSED" if r.refused else ""
            lines.append(
                f"  <- {r.subtask_id} via {r.provider} ({r.latency_s:.2f}s, {r.tokens} tok, conf {r.confidence:.2f}){flag}"
            )
        for e in self.throttle_events:
            lines.append(f"  !! throttling on {e.provider}: {', '.join(e.reasons)}")
        s = self.synthesis
        lines.append(
            f"Scores: {', '.join(f'{k}={v:.2f}' for k, v in s.objective_scores.items())}  J={s.weighted_score:.3f}  "
            f"constraints_met={s.constraints_met} uncertainty={s.uncertainty:.2f} refinements={s.refinements}"
        )
        lines.append("Answer:\n" + s.answer)
        return "\n".join(lines)
