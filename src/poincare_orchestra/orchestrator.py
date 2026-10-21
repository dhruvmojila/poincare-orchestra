"""The end-to-end loop: analyse → decompose → allocate → execute → synthesise → refine."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from poincare_memory import Memory
from pydantic import BaseModel, Field

from .controller import InvestmentScheduler, analyze, decompose
from .ensemble import MockProvider, Provider, Router, ThrottleDetector
from .scenario import ControllerPolicy, Scenario
from .schema import AgentResponse, CompletionRequest, Plan, RunResult, SubTask
from .synthesis import synthesize

logger = logging.getLogger("poincare_orchestra")


class EvalReport(BaseModel):
    """Facet recall and synthesis scores over a scenario's bundled tasks (see :meth:`Orchestrator.evaluate`)."""

    scenario: str
    tasks: int
    facet_recall: float
    mean_weighted_score: float
    constraints_met_rate: float
    throttle_events: int
    per_task: list[dict[str, Any]] = Field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.scenario}: {self.tasks} tasks, facet recall {self.facet_recall:.2f}, "
            f"mean J {self.mean_weighted_score:.3f}, constraints met {self.constraints_met_rate:.0%}, "
            f"throttle events {self.throttle_events}"
        )

    def to_json(self, indent: int | None = 2) -> str:
        """The report as JSON text."""
        return self.model_dump_json(indent=indent)


class Orchestrator:
    """Runs questions through a scenario: the eight steps of the paper's control loop.

    With ``providers=None`` one offline :class:`MockProvider` is created per
    provider name used by the scenario's capability profiles. Pass
    :class:`LiteLLMProvider` instances (or any object satisfying
    :class:`Provider`) for real models; their names should match the
    ``provider`` field of the profiles so that capability matching routes to them.
    """

    def __init__(
        self,
        scenario: Scenario,
        providers: list[Provider] | None = None,
        policy: ControllerPolicy | None = None,
        memory: Memory | None = None,
        clock: Callable[[], datetime] | None = None,
        detector: ThrottleDetector | None = None,
    ) -> None:
        self.scenario = scenario
        self.policy = policy or scenario.policy
        self.memory = memory or scenario.build_memory(clock=clock)
        if providers is None:
            providers = [MockProvider(name) for name in sorted({p.provider for p in scenario.profiles})]
        self.router = Router(providers, scenario.profiles, detector=detector)
        self.scheduler = InvestmentScheduler(self.policy)
        wanted = {p.provider for p in scenario.profiles}
        missing = sorted(wanted - set(self.router.providers))
        if missing:
            logger.warning(
                "scenario %s expects providers %s that were not given; those roles will be load-balanced",
                scenario.name,
                missing,
            )

    def _context(self, st: SubTask, k: int) -> tuple[list[str], list[str], list[float]]:
        """Hierarchy-aware retrieval: the sub-task's branch first, then the entities it names, then global."""
        hits = []
        text = st.query_text or st.question
        if st.branch_id and st.branch_id in self.memory:
            hits += self.memory.search(text, k=k, mode="subtree", root=st.branch_id)
        for eid in st.entity_ids:
            if eid in self.memory:
                hits += self.memory.search(text, k=max(2, k // 2), mode="subtree", root=eid)
        hits += self.memory.search(text, k=max(2, k // 2))
        seen: set[str] = set()
        out = []
        for h in hits:
            if h.time_weight < 1e-3:  # expired or negligible under the temporal policy
                continue
            if h.id not in seen:
                seen.add(h.id)
                out.append(h)
        out = out[:k]
        logger.debug(
            "retrieve %s: %d record(s) from branch=%s entities=%s: %s",
            st.id,
            len(out),
            st.branch_id,
            st.entity_ids,
            [h.id for h in out],
        )
        return [h.text for h in out], [h.id for h in out], [h.time_weight for h in out]

    def _execute(self, st: SubTask, budget: float) -> AgentResponse:
        role = self.scenario.role(st.role) if st.role else self.scenario.roles[0]
        ctx, ids, w = self._context(st, max(2, int(self.policy.retrieval_k * min(2.0, 0.5 + budget))))
        req = CompletionRequest(
            subtask=st,
            role_name=role.name,
            system_prompt=role.system_prompt,
            context=ctx,
            context_ids=ids,
            context_weights=w,
            budget=budget,
        )
        logger.info(
            "execute %s as %s (profile %s, budget %.2f, %d context records)",
            st.id,
            role.name,
            role.profile,
            budget,
            len(ctx),
        )
        return self.router.call(req, role.profile)

    def run(self, question: str) -> RunResult:
        """Answer one question; never raises on provider failures (they become refused responses and events)."""
        logger.info("run: %s", question)
        trace: list[str] = []
        analysis = analyze(question, self.memory, k=self.policy.retrieval_k)
        trace.append(
            f"analyse: intent={analysis.intent} complexity={analysis.complexity:.2f} domains={analysis.domains} entities={analysis.entity_ids}"
        )
        plan: Plan = decompose(
            analysis, self.memory, self.scenario.roles, self.scenario.profiles, self.policy
        )
        alloc = self.scheduler.allocate(plan, self.memory)
        trace.append("allocate: " + ", ".join(f"{k}={v:.2f}" for k, v in alloc.items()))
        responses: list[AgentResponse] = []
        spent = 0.0
        done: set[str] = set()
        pending = [s for s in plan.subtasks if not s.skipped]
        for s_ in plan.subtasks:
            if s_.skipped:
                trace.append(f"skip {s_.id}: does not fit the budget (cost {s_.cost:.2f})")
        while pending:  # run a sub-task once its prerequisites are done
            ready = [s for s in pending if set(s.depends_on) <= done] or pending[:1]
            for st in ready:
                responses.append(self._execute(st, st.budget))
                spent += st.cost
                done.add(st.id)
                pending.remove(st)
        recency = {
            i: float(w)
            for i, w in zip(self.memory.ids, self.memory.time_weights(self.memory.ids), strict=True)
        }
        result = synthesize(
            plan,
            responses,
            recency,
            self.policy.objectives,
            self.policy.constraints,
            spent,
            self.policy.total_budget,
        )
        rounds = 0
        while not result.constraints_met and rounds < self.policy.refine_rounds:
            extra = self.scheduler.reinvest(plan, responses, spent)
            if not extra:
                logger.info("refine: constraints %s violated but no budget remains", result.violated)
                break
            rounds += 1
            trace.append(
                f"refine round {rounds}: violated={result.violated} reinvest={ {k: round(v, 2) for k, v in extra.items()} }"
            )
            logger.info(
                "refine round %d: violated=%s reinvest=%s",
                rounds,
                result.violated,
                {k: round(v, 2) for k, v in extra.items()},
            )
            for sid, b in extra.items():
                st = next(s for s in plan.subtasks if s.id == sid)
                responses = [r for r in responses if r.subtask_id != sid] + [self._execute(st, b)]
                spent += st.cost * 0.5
            result = synthesize(
                plan,
                responses,
                recency,
                self.policy.objectives,
                self.policy.constraints,
                spent,
                self.policy.total_budget,
                refinements=rounds,
            )
        trace.append(f"synthesise: J={result.weighted_score:.3f} constraints_met={result.constraints_met}")
        logger.info(
            "synthesise: J=%.3f constraints_met=%s uncertainty=%.2f claims=%d refinements=%d",
            result.weighted_score,
            result.constraints_met,
            result.uncertainty,
            len(result.claims),
            rounds,
        )
        return RunResult(
            question=question,
            plan=plan,
            responses=responses,
            synthesis=result,
            allocations=alloc,
            throttle_events=list(self.router.events),
            trace=trace,
        )

    def evaluate(self) -> EvalReport:
        """Run every bundled task and measure facet recall (expected substrings found in the answer and responses)."""
        per_task = []
        recalls, scores, mets = [], [], []
        for task in self.scenario.tasks:
            res = self.run(task.question)
            text = (res.synthesis.answer + " " + " ".join(r.content for r in res.responses)).lower()
            found = [f for f in task.expected_facets if f.lower() in text]
            recall = len(found) / max(1, len(task.expected_facets))
            recalls.append(recall)
            scores.append(res.synthesis.weighted_score)
            mets.append(1.0 if res.synthesis.constraints_met else 0.0)
            missing = [f for f in task.expected_facets if f not in found]
            logger.info(
                "eval: recall=%.2f J=%.3f missing=%s  %s",
                recall,
                res.synthesis.weighted_score,
                missing,
                task.question,
            )
            per_task.append(
                {
                    "question": task.question,
                    "facet_recall": recall,
                    "missing": missing,
                    "J": res.synthesis.weighted_score,
                    "subtasks": len(res.plan.subtasks),
                }
            )
        n = max(1, len(self.scenario.tasks))
        return EvalReport(
            scenario=self.scenario.name,
            tasks=len(self.scenario.tasks),
            facet_recall=sum(recalls) / n,
            mean_weighted_score=sum(scores) / n,
            constraints_met_rate=sum(mets) / n,
            throttle_events=len(self.router.events),
            per_task=per_task,
        )
