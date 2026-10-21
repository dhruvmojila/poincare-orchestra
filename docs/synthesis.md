# Synthesis

Response synthesis (paper §III-D and §IV-E) turns the sub-task responses into one answer and decides whether it is good enough. `synthesize()` does four things: fuse claims, score five objectives, apply the weighted-sum objective with epsilon constraints (eq. 7), and estimate uncertainty. `Orchestrator.run` then refines while a constraint fails and budget remains.

## Claim fusion

Every non-refused response contributes its `Claim`s. Claims are embedded with the same offline `HashingEmbedder` (128 dimensions) and merged greedily: a claim joins an existing fused claim when the cosine similarity of their embeddings is at least `merge_threshold` (default 0.85). The fused claim keeps the first text, the **maximum** confidence, and the **union** of the sources (sorted). Fused claims are sorted by confidence, then text.

```python
from poincare_orchestra import AgentResponse, Claim, fuse_claims

responses = [
    AgentResponse(
        subtask_id="q1",
        role="tier2",
        provider="provider-a",
        content="The limit is 250 requests per second.",
        tokens=30,
        sources=["rate_new"],
        claims=[
            Claim(text="API rate limit is 250 requests per second", confidence=0.9, sources=["rate_new"]),
        ],
    ),
    AgentResponse(
        subtask_id="q2",
        role="tier1",
        provider="provider-b",
        content="250 rps per project; tokens expire after 60 minutes.",
        tokens=30,
        sources=["rate_new", "rel24", "auth"],
        claims=[
            Claim(
                text="API rate limit is 250 requests per second per project",
                confidence=0.7,
                sources=["rate_new", "rel24"],
            ),
            Claim(text="Tokens expire after 60 minutes", confidence=0.8, sources=["auth"]),
        ],
    ),
]
for claim in fuse_claims(responses):
    print(claim.confidence, claim.sources, claim.text)
```

```text
0.9 ['rate_new', 'rel24'] API rate limit is 250 requests per second
0.8 ['auth'] Tokens expire after 60 minutes
```

The two rate-limit claims differ by two words and merge; the merged claim carries both providers' sources.

## The five objectives

`score_objectives()` computes the objective functions \(f_i(R)\) of eq. 7, each in \([0, 1]\):

| Objective | Definition | What it rewards |
|---|---|---|
| `coverage` | answered sub-tasks ÷ all sub-tasks in the plan (skipped ones count as unanswered); a sub-task is answered when a non-refused response with at least one claim exists | investigating every facet of the question |
| `density` | min(1, fused claims ÷ (non-refused tokens ÷ 60)) | distinct information per token, the paper's bits-per-token notion |
| `agreement` | mean pairwise Jaccard overlap of the *source ids* cited by the non-refused responses; 1.0 with a single response, 0.0 with none | independent responses converging on the same records |
| `recency` | mean time weight (from the memory's decay policy) of every source cited by the fused claims | answers built on current records |
| `cost` | clip(1 − spent ÷ `total_budget`, 0, 1) | budget left over |

"Spent" is the sum of the executed sub-tasks' costs, plus half a sub-task's cost for every refinement re-run.

## The objective (eq. 7)

The paper formulates response optimisation as a weighted sum under epsilon constraints:

$$\max_{R}\; J(R) = \sum_{i=1}^{m} w_i f_i(R) \quad \text{s.t.} \quad f_j(R) \geq \epsilon_j,\ \forall j$$

`weighted_sum(obj, weights, constraints)` returns \(J\) normalised by the sum of the weights, whether every constraint holds, and the list of violated objectives. Weights \(w_i\) are `ControllerPolicy.objectives` and thresholds \(\epsilon_j\) are `ControllerPolicy.constraints`; both are validated against the five objective names.

```python
from poincare_orchestra import ControllerPolicy, weighted_sum

policy = ControllerPolicy()
print(policy.objectives, policy.constraints)
print(
    weighted_sum(
        {"coverage": 0.67, "density": 1.0, "agreement": 0.0, "recency": 1.0, "cost": 0.2},
        policy.objectives,
        policy.constraints,
    )
)
print(
    weighted_sum(
        {"coverage": 0.33, "density": 0.1, "agreement": 1.0, "recency": 1.0, "cost": 0.9},
        policy.objectives,
        policy.constraints,
    )
)
```

```text
{'coverage': 0.4, 'density': 0.2, 'agreement': 0.1, 'recency': 0.15, 'cost': 0.15} {'coverage': 0.5, 'density': 0.2}
(0.648, True, [])
(0.537, False, ['coverage', 'density'])
```

The second response has a respectable \(J\) but violates both constraints: a cheap, agreeing answer that covers a third of the question is not acceptable, which is what the epsilon constraints are for.

## Uncertainty

`SynthesisResult.uncertainty` is a proxy in \([0, 1]\): \(1 - \bar{c}\,(1 - r)\) where \(\bar{c}\) is the mean confidence of the fused claims and \(r\) the share of refused responses; with no claims at all it is 1.0. Cross-provider disagreement is reported separately as the `agreement` objective rather than folded in, so the two signals stay interpretable.

## End to end

`synthesize()` takes the plan, the responses, the memory's time weights, the policy's weights and constraints, and the budget position:

```python
from poincare_orchestra import ControllerPolicy, Plan, SubTask, synthesize

plan = Plan(
    query="What is the current API rate limit?",
    intent="factual",
    complexity=0.3,
    subtasks=[
        SubTask(id="q1", question="rate limit (focus: api)"),
        SubTask(id="q2", question="rate limit (focus: tickets)"),
        SubTask(id="q3", question="rate limit (focus: storage)"),
    ],
)
policy = ControllerPolicy()
result = synthesize(
    plan,
    responses,
    {"rate_new": 1.0, "rel24": 0.8, "auth": 1.0},
    policy.objectives,
    policy.constraints,
    spent=2.5,
    budget=6.0,
)
print({k: round(v, 3) for k, v in result.objective_scores.items()})
print(round(result.weighted_score, 3), result.constraints_met, result.violated, round(result.uncertainty, 3))
print(result.answer)
```

```text
{'coverage': 0.667, 'density': 1.0, 'agreement': 0.333, 'recency': 0.933, 'cost': 0.583}
0.727 True [] 0.15
Synthesis across 2 perspective(s): tier1, tier2.
- (0.90) API rate limit is 250 requests per second [rate_new, rel24]
- (0.80) Tokens expire after 60 minutes [auth]
Open sub-questions: rate limit (focus: storage)
```

Coverage is 2/3 because `q3` has no response. Agreement is the Jaccard overlap of the two responses' `sources` lists, {rate_new} and {rate_new, rel24, auth}: 1/3. Recency is the mean weight of the records the fused claims cite (1.0, 0.8, 1.0). Cost is 1 − 2.5/6.0. With the default weights, J = 0.4·0.667 + 0.2·1.0 + 0.1·0.333 + 0.15·0.933 + 0.15·0.583 ≈ 0.727, both constraints hold, and uncertainty is 1 − 0.85 (the mean fused confidence) with no refusals. The composed answer names the contributing roles, lists the fused claims with their supporting record ids, and ends with the open sub-questions.

## Refinement

After the first synthesis, `Orchestrator.run` loops while `constraints_met` is false and fewer than `policy.refine_rounds` rounds have run:

1. `InvestmentScheduler.reinvest` measures each response's yield (distinct claims per 100 tokens) and splits the remaining budget over the lower-yielding half of the sub-tasks.
2. Those sub-tasks are executed again with the extra budget (a larger budget retrieves more context), and their previous responses are replaced.
3. `spent` grows by half the sub-task's cost per re-run, and the synthesis is recomputed with `refinements` incremented.

If no budget remains the loop stops and the result reports the violated constraints. The refinement rounds appear in `RunResult.trace` (`refine round 1: violated=[...] reinvest={...}`) and in the INFO log.
