# Controller

The metacognitive controller (paper §III-B, §III-C and §IV-B) has four executive functions: query analysis, hierarchical decomposition, capability matching and resource allocation. The implementation is rule-based and offline so that every decision is inspectable and testable; an LLM-backed planner can replace `decompose` without touching the rest ([Replacing the planner](#replacing-the-planner)).

## Analysis

`analyze(query, memory, k=5)` returns a `QueryAnalysis` with the intent, a complexity score, the memory branches and domains the question touches, the named entities, the retrieved record ids and the clauses.

**Intent** is the first matching pattern, in this order:

| Intent | Matched when the question contains |
|---|---|
| `planning` | plan, recommend, should, design, schedule, program, "next two/2/few weeks", "how do/can/should I/we" |
| `comparison` | compare, versus, vs, difference, better, rather than |
| `explanation` | why, explain, how does, mechanism, because |
| `factual` | none of the above |

**Clauses** are split on `;`, *then*, *and then*, *and also*, *as well as*, and sentence boundaries followed by a capital letter; fragments of three characters or fewer are dropped.

**Branches and domains.** Two searches of `k` results each run against the memory: one over *structural* records (those whose `meta.kind` is not in `EPHEMERAL_KINDS = {event, ticket, issue, case, observation}`) and one over the dated, ephemeral ones. Each hit, and each entity hit, is mapped to its **branch**: the ancestor one level below the root (`branch_of`). Roots themselves never count as a branch. The branch's `meta.domain` (or the text before its first colon) is the domain label.

**Entities.** `entity_hits` returns records with a parent whose leading phrase (the text before `:` or `(`, 2–24 characters) occurs in the lower-cased question. The convention `"Athlete A: ..."`, `"Ticket 4411: ..."`, `"Release 2.4 (...)"` in the scenario text is what makes this work.

**Complexity** is `clip(0.15 · clauses + 0.12 · branches + 0.01 · words + 0.2 · [intent is planning], 0, 1)`.

```python
from poincare_orchestra import analyze, load_scenario

scenario = load_scenario("support_kb")
memory = scenario.build_memory()
analysis = analyze(
    "Which Kafka version does the connector require now, and why might it fail after an upgrade?",
    memory,
    k=scenario.policy.retrieval_k,
)
print(analysis.intent, round(analysis.complexity, 2), analysis.domains, analysis.entity_ids)
```

```text
explanation 0.91 ['storage', 'ingestion', 'api', 'tickets', 'releases'] []
```

## Decomposition (eq. 5)

The paper decomposes a query into coordinated sub-tasks:

$$Q \rightarrow \{q_1, q_2, \ldots, q_n\}$$

`decompose(analysis, memory, roles, profiles, policy)` builds the `Plan`:

1. One **facet sub-task** per branch, phrased as the question plus `(focus: <domain>)` and carrying `branch_id` so that retrieval starts in that subtree.
2. If the question has more than one clause, one **clause sub-task** per clause, each depending on the previous one (`depends_on`), so that "explain X and then recommend Y" runs in order.
3. Duplicates (by lower-cased text) are dropped and the list is capped at `policy.max_subtasks`; a question that produced nothing becomes a single sub-task.
4. Every sub-task carries the analysis' `entity_ids` so retrieval can look inside the named entities' subtrees.

```python
from poincare_orchestra import ControllerPolicy, analyze, decompose, load_scenario

scenario = load_scenario("sprint_coaching")
memory = scenario.build_memory()
analysis = analyze(
    "Athlete A shows forward trunk lean at the end of the race; explain the injury implication and then recommend a drill.",
    memory,
)
print(analysis.intent, analysis.clauses)
roomy = ControllerPolicy(max_subtasks=6, total_budget=8.0)
plan = decompose(analysis, memory, scenario.roles, scenario.profiles, roomy)
for st in plan.subtasks:
    print(st.id, st.role, st.depends_on, st.question)
```

```text
planning ['Athlete A shows forward trunk lean at the end of the race', 'explain the injury implication', 'recommend a drill.']
q1 biomechanist [] Athlete A shows forward trunk lean at the end of the race; explain the injury implication and then recommend a drill. (focus: biomechanics)
q2 physiologist [] Athlete A shows forward trunk lean at the end of the race; explain the injury implication and then recommend a drill. (focus: physiology)
q3 strength_coach [] Athlete A shows forward trunk lean at the end of the race; explain the injury implication and then recommend a drill. (focus: athletes)
q4 physiologist [] Athlete A shows forward trunk lean at the end of the race
q5 physiologist ['q4'] explain the injury implication
q6 physiologist ['q5'] recommend a drill.
```

With the scenario's own `max_subtasks=4` the plan stops after `q4`, which is what the bundled evaluation runs. `Orchestrator.run` executes sub-tasks whose dependencies are done first and falls back to the first pending one if a cycle ever appeared.

## Capability matching

Each sub-task goes to the role with the highest score

`score(role) = |role.domains ∩ subtask.domains| + profile.fit(subtask.domains, intent)`

where the role's `CapabilityProfile` contributes

`fit = 0.6 · domain_score + 0.4 · intent_weight`

with `domain_score` the share of the sub-task's domains the profile lists (0.5 when the sub-task has no domains) and `intent_weight` the profile's `reasoning` for planning and comparison, the mean of `reasoning` and `creativity` for explanation, and `reliability` for factual questions. The sub-task's cost is the profile's `cost_per_call × (1 + complexity)`. This is the *static* side of the paper's capability matching; the dynamic side (provider health) lives in the [Router](ensemble.md#router).

## Investment scheduler (eq. 6)

The paper allocates resources to the investment with the best expected information gain per cost:

$$I^*(q_i) = \arg\max_{I} \frac{G(q_i, I)}{C(I)}$$

`InvestmentScheduler` instantiates the symbols as follows.

**Expected gain** \(G\): for each sub-task, `relevance` is the mean of \(e^{-d}\) over the top-3 hits of the sub-task question inside its branch subtree (globally if it has none; 0.1 with no hits), and `novelty` is one minus the highest cosine similarity between the sub-task question and the other sub-task questions (hashing embeddings, 128 dimensions). Then

`G = clip(0.2 + 0.8 · relevance · (0.5 + 0.5 · novelty), 0.05, 1)`

so a sub-task gains more when the memory holds relevant material *and* the sub-task is not a rephrasing of another.

**Cost** \(C\) is the sub-task cost from capability matching.

**Allocation and the skip rule.** Sub-tasks are sorted by \(G / C\). They are kept in that order while the sum of their costs fits `policy.total_budget` (the first one is always kept); the rest are marked `skipped` with budget 0 — the allocation decision of eq. 6 made explicit instead of overspending or under-funding everything. Each kept sub-task receives a floor of `min(policy.min_budget, total_budget / kept)` and the remainder is split in proportion to \(G / C\), so the budgets sum to `total_budget`.

```python
from poincare_orchestra import InvestmentScheduler, analyze, decompose, load_scenario

scenario = load_scenario("support_kb")
memory = scenario.build_memory()
analysis = analyze(
    "Which Kafka version does the connector require now, and why might it fail after an upgrade?",
    memory,
    k=scenario.policy.retrieval_k,
)
plan = decompose(analysis, memory, scenario.roles, scenario.profiles, scenario.policy)
for st in plan.subtasks:
    print(st.id, st.role, st.domains, round(st.cost, 2))
allocation = InvestmentScheduler(scenario.policy).allocate(plan, memory)
print({k: round(v, 2) for k, v in allocation.items()}, [st.id for st in plan.subtasks if st.skipped])
```

```text
q1 tier2 ['storage'] 2.29
q2 tier2 ['ingestion'] 2.29
q3 tier2 ['api'] 2.29
{'q2': 3.02, 'q1': 2.98} ['q3']
```

Each sub-task costs 1.2 × (1 + 0.91) = 2.29. Two fit the scenario's budget of 6.0 (4.58); the third would bring the total to 6.87, so it is skipped. The two kept sub-tasks get a floor of 0.5 each and share the remaining 5.0 almost equally, because their gains are nearly identical.

**Yield and re-investment.** After execution, `measure_yield` scores each response as distinct claims per 100 tokens (0 for refusals), and `reinvest` splits whatever budget is left equally over the lower-yielding half of the sub-tasks. `Orchestrator.run` uses this during [refinement](synthesis.md#refinement).

## Replacing the planner

`decompose` returns a plain `Plan`: `query`, `intent`, `complexity`, `domains`, `entities` and a list of `SubTask`s with `id`, `question`, `role`, `depends_on`, `domains`, `branch_id` and `entity_ids`. Anything that produces such a plan — an LLM prompted with the memory's `tree()` and the role list, for example — can replace it; the scheduler, retrieval, router and synthesis consume the `Plan` and nothing else.
