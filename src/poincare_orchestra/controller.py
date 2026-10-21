"""Metacognitive controller (paper §III-B, §III-C, §IV-B).

Four executive functions, each a small, inspectable step:
1. query analysis and intent recognition, with the memory hierarchy as the domain model;
2. hierarchical decomposition into coordinated sub-tasks ``Q -> {q_1..q_n}`` (eq. 5);
3. capability matching of sub-tasks to roles and profiles;
4. resource allocation by expected information gain per cost,
   ``I*(q_i) = argmax_I G(q_i, I) / C(I)`` (eq. 6), run as an investment cycle:
   invest, measure yield, re-invest the remainder.

The implementation is rule-based and offline so the control loop is transparent;
an LLM-backed planner can replace ``decompose`` without touching the rest.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np
from poincare_memory import HashingEmbedder, Memory

from .profiles import AgentRole, CapabilityProfile
from .scenario import ControllerPolicy
from .schema import AgentResponse, Plan, SubTask

logger = logging.getLogger("poincare_orchestra")

_INTENTS = [
    (
        "planning",
        re.compile(
            r"\b(plan|recommend|should|design|schedule|program|next (two|2|few) weeks|how (do|can|should) (i|we))\b",
            re.I,
        ),
    ),
    ("comparison", re.compile(r"\b(compare|versus|vs\.?|difference|better|rather than)\b", re.I)),
    ("explanation", re.compile(r"\b(why|explain|how does|mechanism|because)\b", re.I)),
]
_SPLIT = re.compile(r"\s*(?:;|\bthen\b|\band then\b|\.\s+(?=[A-Z])|\band also\b|\bas well as\b)\s*", re.I)
EPHEMERAL_KINDS = {"event", "ticket", "issue", "case", "observation"}


@dataclass
class QueryAnalysis:
    """Result of :func:`analyze`: intent, complexity, the memory branches and entities a query touches."""

    query: str
    intent: str
    complexity: float
    domains: list[str]
    branch_ids: list[str]
    entity_ids: list[str]
    retrieved_ids: list[str]
    clauses: list[str]


def entity_hits(query: str, memory: Memory, max_prefix: int = 24) -> list[str]:
    """Records whose leading phrase (the text before ':' or '(') names an entity mentioned in the query.

    Convention: entity records read ``"Athlete A: ..."``, ``"Ticket 4411: ..."``, ``"Release 2.4 (...)"``.
    """
    q = query.lower()
    hits: list[str] = []
    for rec in memory:
        head = rec.text.split(":")[0].split("(")[0].strip()
        if 2 <= len(head) <= max_prefix and head.lower() in q and rec.parent_id is not None:
            hits.append(rec.id)
    return hits


def branch_of(memory: Memory, id_: str) -> str:
    """The ancestor one level below the root (the domain branch), or the node itself."""
    anc = memory.ancestors(id_)
    return anc[-2] if len(anc) >= 2 else id_


def analyze(query: str, memory: Memory, k: int = 5) -> QueryAnalysis:
    """Intent, complexity, domain branches and named entities for a query."""
    intent = "factual"
    for name, rx in _INTENTS:
        if rx.search(query):
            intent = name
            break
    clauses = [c.strip() for c in _SPLIT.split(query) if c and len(c.strip()) > 3]
    # structural knowledge defines the domains; dated records and named entities refine them
    structural = memory.search(
        query, k=k, touch=False, filters=lambda r: r.meta.get("kind") not in EPHEMERAL_KINDS
    )
    ephemeral = memory.search(
        query, k=k, touch=False, filters=lambda r: r.meta.get("kind") in EPHEMERAL_KINDS
    )
    entities = entity_hits(query, memory)
    branches: list[str] = []
    for id_ in [h.id for h in structural] + entities + [h.id for h in ephemeral]:
        b = branch_of(memory, id_)
        if b not in branches and memory.level(b) >= 1:
            branches.append(b)
    words = len(re.findall(r"\w+", query))
    complexity = float(
        np.clip(
            0.15 * len(clauses)
            + 0.12 * len(branches)
            + 0.01 * words
            + (0.2 if intent == "planning" else 0.0),
            0.0,
            1.0,
        )
    )
    domains = [str(memory.get(b).meta.get("domain", memory.get(b).text.split(":")[0][:40])) for b in branches]
    logger.info(
        "analyse: intent=%s complexity=%.2f domains=%s entities=%s clauses=%d",
        intent,
        complexity,
        domains,
        entities,
        len(clauses),
    )
    logger.debug("analyse: branches=%s retrieved=%s", branches, [h.id for h in structural + ephemeral])
    return QueryAnalysis(
        query=query,
        intent=intent,
        complexity=complexity,
        domains=domains,
        branch_ids=branches,
        entity_ids=entities,
        retrieved_ids=[h.id for h in structural + ephemeral],
        clauses=clauses,
    )


def decompose(
    analysis: QueryAnalysis,
    memory: Memory,
    roles: list[AgentRole],
    profiles: list[CapabilityProfile],
    policy: ControllerPolicy,
) -> Plan:
    """Split a query into facet sub-tasks (one per domain branch) and sequential clause sub-tasks, then match roles."""
    subtasks: list[SubTask] = []
    seen: set[str] = set()

    def add(
        question: str,
        domains: list[str],
        depends: list[str],
        branch: str | None = None,
        query_text: str | None = None,
    ) -> None:
        key = question.lower()
        if key in seen or len(subtasks) >= policy.max_subtasks:
            return
        seen.add(key)
        subtasks.append(
            SubTask(
                id=f"q{len(subtasks) + 1}",
                question=question,
                domains=domains,
                depends_on=depends,
                branch_id=branch,
                entity_ids=list(analysis.entity_ids),
                query_text=query_text or question,
            )
        )

    for d, b in zip(analysis.domains, analysis.branch_ids, strict=True):
        add(f"{analysis.query} (focus: {d})", [d], [], branch=b, query_text=analysis.query)
    if len(analysis.clauses) > 1:  # "A, then B" becomes dependent sub-tasks
        prev: list[str] = []
        for clause in analysis.clauses[: policy.max_subtasks]:
            before = len(subtasks)
            add(clause, analysis.domains, list(prev))
            if len(subtasks) > before:
                prev = [subtasks[-1].id]
    if not subtasks:
        add(analysis.query, analysis.domains, [])

    prof_by_name = {p.name: p for p in profiles}
    for st in subtasks:
        best: AgentRole | None = None
        best_score = -1.0
        for role in roles:
            prof = prof_by_name[role.profile]
            overlap = len({x.lower() for x in st.domains} & {x.lower() for x in role.domains})
            score = overlap + prof.fit(st.domains, analysis.intent)
            if score > best_score:
                best, best_score = role, score
        if best is not None:
            st.role = best.name
            st.cost = prof_by_name[best.profile].cost_per_call * (1.0 + analysis.complexity)
            logger.debug(
                "match %s -> role=%s (score %.2f, cost %.2f): %s",
                st.id,
                st.role,
                best_score,
                st.cost,
                st.question,
            )
    logger.info(
        "decompose: %d sub-task(s) from %d clause(s) and %d branch(es)",
        len(subtasks),
        len(analysis.clauses),
        len(analysis.branch_ids),
    )
    return Plan(
        query=analysis.query,
        intent=analysis.intent,
        complexity=analysis.complexity,
        domains=analysis.domains,
        entities=analysis.entity_ids,
        subtasks=subtasks,
    )


class InvestmentScheduler:
    """Allocate compute by expected information gain per cost (eq. 6), then re-invest after measuring yield."""

    def __init__(self, policy: ControllerPolicy, embedder: HashingEmbedder | None = None) -> None:
        self.policy = policy
        self.embedder = embedder or HashingEmbedder(dim=128)

    def expected_gain(self, plan: Plan, memory: Memory) -> dict[str, float]:
        """Gain = relevance of what the memory holds for the sub-task × novelty versus the other sub-tasks."""
        if not plan.subtasks:
            return {}
        E = self.embedder.embed([st.question for st in plan.subtasks])
        sims = E @ E.T
        gains: dict[str, float] = {}
        for i, st in enumerate(plan.subtasks):
            if st.branch_id and st.branch_id in memory:
                hits = memory.search(
                    st.query_text or st.question, k=3, mode="subtree", root=st.branch_id, touch=False
                )
            else:
                hits = memory.search(st.query_text or st.question, k=3, touch=False)
            relevance = float(np.mean([np.exp(-h.distance) for h in hits])) if hits else 0.1
            others = [sims[i, j] for j in range(len(plan.subtasks)) if j != i]
            novelty = 1.0 - (max(others) if others else 0.0)
            gains[st.id] = float(np.clip(0.2 + 0.8 * relevance * (0.5 + 0.5 * novelty), 0.05, 1.0))
        return gains

    def allocate(self, plan: Plan, memory: Memory) -> dict[str, float]:
        """Keep sub-tasks in order of gain/cost while they fit the budget, then split the budget by gain/cost.

        Sub-tasks that do not fit are marked ``skipped`` with budget 0: the
        allocation decision of eq. 6 made explicit instead of overspending.
        """
        gains = self.expected_gain(plan, memory)
        total = self.policy.total_budget
        order = sorted(plan.subtasks, key=lambda st: -gains[st.id] / max(st.cost, 1e-6))
        kept: list[SubTask] = []
        cum = 0.0
        for st in order:
            st.expected_gain = gains[st.id]
            if not kept or cum + st.cost <= total:
                kept.append(st)
                cum += st.cost
            else:
                st.skipped = True
                st.budget = 0.0
        ratios = {st.id: gains[st.id] / max(st.cost, 1e-6) for st in kept}
        floor = min(self.policy.min_budget, total / max(1, len(kept)))
        remaining = max(0.0, total - floor * len(kept))
        s = sum(ratios.values()) or 1.0
        alloc = {sid: floor + remaining * r / s for sid, r in ratios.items()}
        for st in kept:
            st.budget = alloc[st.id]
        skipped = [st.id for st in plan.subtasks if st.skipped]
        logger.info(
            "allocate: %s%s",
            ", ".join(f"{k}={v:.2f}" for k, v in alloc.items()),
            f" skipped={skipped}" if skipped else "",
        )
        return alloc

    @staticmethod
    def measure_yield(response: AgentResponse) -> float:
        """Information yield proxy: distinct claims per 100 tokens (the paper's 'information density')."""
        if response.refused or response.tokens == 0:
            return 0.0
        return min(1.0, len({c.text.lower() for c in response.claims}) / max(1.0, response.tokens / 100.0))

    def reinvest(self, plan: Plan, responses: list[AgentResponse], spent: float) -> dict[str, float]:
        """Extra budget for the sub-tasks with the lowest yield (refinement targets)."""
        remaining = max(0.0, self.policy.total_budget - spent)
        if remaining <= 0 or not responses:
            return {}
        yields = {r.subtask_id: self.measure_yield(r) for r in responses}
        worst = sorted(yields, key=lambda k: yields[k])[: max(1, len(yields) // 2)]
        logger.info(
            "reinvest: %.2f remaining over %s (yields %s)",
            remaining,
            worst,
            {k: round(v, 2) for k, v in yields.items()},
        )
        return {sid: remaining / len(worst) for sid in worst}
