# Getting started

## Install

```bash
pip install poincare-orchestra                # core; pulls poincare-memory, pydantic, numpy
pip install 'poincare-orchestra[yaml]'        # + PyYAML for YAML scenario files
pip install 'poincare-orchestra[litellm]'     # + LiteLLM for real models
```

Python 3.10 or newer. Nothing needs a GPU or network access until you plug in a real model.

For development:

```bash
git clone https://github.com/dhruvmojila/poincare-orchestra && cd poincare-orchestra
uv venv && uv pip install -e ".[dev]"
pytest && ruff check . && ruff format --check . && mypy && mkdocs build --strict
```

## First run

```bash
poincare-orchestra run sprint_coaching "Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks."
```

This runs the question through the bundled `sprint_coaching` scenario with two offline mock providers and prints `RunResult.explain()`:

```text
Question: Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks.
Intent: planning  complexity=1.00  domains=['strength', 'athletes', 'biomechanics', 'physiology']  entities=['athlete_a', 'a_better']
  [q1] role=strength_coach gain=0.32 cost=1.20 budget=3.18  Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks. (focus: strength)
  [q2] role=strength_coach gain=0.33 cost=1.20 budget=3.26  Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks. (focus: athletes)
  [q3] role=biomechanist gain=0.31 cost=3.00 budget=1.56  Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks. (focus: biomechanics)
  [q4] role=physiologist gain=0.31 cost=3.00 budget=0.00 SKIPPED (budget)  Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks. (focus: physiology)
  <- q1 via provider-b (0.01s, 201 tok, conf 0.67)
  <- q2 via provider-b (0.01s, 164 tok, conf 0.67)
  <- q3 via provider-a (0.01s, 149 tok, conf 0.77)
Scores: coverage=0.75, density=1.00, agreement=0.07, recency=0.93, cost=0.32  J=0.695  constraints_met=True uncertainty=0.27 refinements=0
Answer:
Synthesis across 2 perspective(s): biomechanist, strength_coach.
- (0.95) Athlete A: hamstring flexibility improved after two weeks of eccentric work; no pain during 300 m repeats [a_better]
- (0.95) Hamstring strains occur mostly in late swing, when the hamstrings decelerate the swinging leg before ground contact under high eccentric load [late_swing]
- (0.95) Nordic hamstring curls reduce hamstring strain risk; progress from 2 x 4 to 3 x 8 repetitions over four weeks [nordic]
- (0.88) Athlete A: 400 m personal best 47.2 s, right-leg dominant, history of left hamstring strain in 2025 [athlete_a]
  ... (17 more claims)
Open sub-questions: Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks. (focus: physiology)
```

Latencies are measured with a real clock, so the `0.01s` figures vary a little between runs; everything else is deterministic.

## Reading the trace line by line

**`Question:`** — the question as asked.

**`Intent: planning  complexity=1.00  domains=[...]  entities=[...]`** — the output of query analysis ([Controller › Analysis](controller.md#analysis)). The intent is one of `planning`, `comparison`, `explanation` or `factual`; here the word *Plan* matched the planning pattern. Complexity is a clipped linear score of clause count, branch count, word count and intent, so a long planning question saturates at `1.00`. Domains are the labels of the memory branches the question touches (the branch's `meta.domain`), in retrieval order. Entities are records whose leading phrase appears in the question: both `athlete_a` ("Athlete A: 400 m personal best…") and `a_better` ("Athlete A: hamstring flexibility improved…") begin with "Athlete A".

**`[q1] role=strength_coach gain=0.32 cost=1.20 budget=3.18  … (focus: strength)`** — one line per sub-task of the plan (eq. 5). The controller made one *facet* sub-task per domain branch; questions with several clauses also get *clause* sub-tasks that depend on each other (`after ['q1']`). `role` is the matched role (domain overlap plus the capability profile's fit for the intent). `cost` is the profile's `cost_per_call × (1 + complexity)`: 0.6 × 2 = 1.20 for the `fast-specialist` profile and 1.5 × 2 = 3.00 for `deep-reasoner`. `gain` is the expected information gain (relevance of what the memory holds × novelty against the other sub-tasks) and `budget` the share of `policy.total_budget` allocated by gain per cost (eq. 6).

**`SKIPPED (budget)`** — q4 did not fit: the first three cost 1.20 + 1.20 + 3.00 = 5.40 and adding 3.00 would exceed the scenario's budget of 8.0, so it is skipped rather than under-funded and shows up later as an open sub-question.

**`<- q1 via provider-b (0.01s, 201 tok, conf 0.67)`** — one line per response: which provider the router chose (the `fast-specialist` profile prefers `provider-b`), latency, token count and the mean confidence of the response's claims. A refused response carries the flag `REFUSED`.

**`!! throttling on provider-a: …`** — printed for every throttle event: a response that broke the provider's baseline (refusal, latency, length or density) or a provider exception (`error: <type>`). None occurred here; [Ensemble](ensemble.md#router) shows runs that have them.

**`Scores: coverage=0.75, density=1.00, agreement=0.07, recency=0.93, cost=0.32  J=0.695 …`** — the five objectives of the synthesis ([Synthesis › Objectives](synthesis.md#the-five-objectives)): 3 of 4 sub-tasks answered gives coverage 0.75; density is claims per 60 tokens, clipped to 1; agreement is the mean pairwise overlap of cited sources between responses (the three responses cited mostly different records); recency is the mean time weight of the cited records (dated observations decay with the scenario's 30-day half-life); cost is 1 − spent/budget = 1 − 5.40/8.0. `J` is the weighted sum of eq. 7 with the policy's weights (0.4, 0.2, 0.1, 0.15, 0.15): 0.4·0.75 + 0.2·1.00 + 0.1·0.07 + 0.15·0.93 + 0.15·0.32 ≈ 0.695. `constraints_met=True` means every epsilon constraint held (by default coverage ≥ 0.5 and density ≥ 0.2), so no refinement round ran (`refinements=0`). `uncertainty` falls with claim confidence and rises with refusals.

**`Answer:`** — the composed answer: which roles contributed, the fused claims sorted by confidence with the ids of the memory records that support them, and the open sub-questions that were skipped or unanswered.

## The same from Python

```python
from poincare_orchestra import Orchestrator, load_scenario

scenario = load_scenario("sprint_coaching")
orchestrator = Orchestrator(scenario)  # offline mock providers, one per provider name in the profiles
result = orchestrator.run("Is Athlete B ready to resume plyometrics?")
print(result.explain())
```

`RunResult` is a Pydantic model, so every part of the trace is data:

```python
for st in result.plan.subtasks:
    print(st.id, st.role, round(st.expected_gain, 2), round(st.budget, 2), st.skipped)
print(result.synthesis.objective_scores)
print(round(result.synthesis.weighted_score, 3), result.synthesis.constraints_met)
print([claim.text for claim in result.synthesis.claims][:2])
print(result.trace)  # the controller's own log of what it decided
```

Serialise and restore a run (the JSON contains the plan, every response, the synthesis, the allocations, the throttle events and the trace):

```python
from poincare_orchestra import RunResult

text = result.to_json()
assert RunResult.from_json(text) == result
```

## Watching the stages

The package logs to the `poincare_orchestra` logger: INFO for each stage, DEBUG for retrieval details and per-provider answers, WARNING for provider errors. On the command line, `-v` shows INFO and `-vv` DEBUG on stderr:

```bash
poincare-orchestra -v run support_kb "Which Kafka version does the connector require now, and why might it fail after an upgrade?"
```

```text
INFO run: Which Kafka version does the connector require now, and why might it fail after an upgrade?
INFO analyse: intent=explanation complexity=0.91 domains=['storage', 'ingestion', 'api', 'tickets', 'releases'] entities=[] clauses=1
INFO decompose: 3 sub-task(s) from 1 clause(s) and 5 branch(es)
INFO allocate: q2=3.02, q1=2.98 skipped=['q3']
INFO execute q1 as tier2 (profile tier2-model, budget 2.98, 6 context records)
INFO execute q2 as tier2 (profile tier2-model, budget 3.02, 7 context records)
INFO synthesise: J=0.693 constraints_met=True uncertainty=0.18 claims=9 refinements=0
```

In Python, configure logging as usual:

```python
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logging.getLogger("poincare_orchestra").setLevel(logging.DEBUG)
```

## Simulating trouble

The mock providers can misbehave on demand, which is how the ensemble's detector and failover are exercised without a network:

```bash
poincare-orchestra run support_kb "What is the current API rate limit?" --fail-after 0
```

prints a `!! throttling on provider-a: error: RuntimeError` line and answers from `provider-b`; see [Ensemble](ensemble.md) for `--degrade-after` and the detector's signals.

## Next steps

- [Scenarios](scenarios.md): what a scenario contains and how to write your own in YAML.
- [Controller](controller.md), [Ensemble](ensemble.md), [Synthesis](synthesis.md): the three components and the paper's equations.
- [Evaluation](evaluation.md): the harness and the current numbers.
- [CLI](cli.md): every command and flag.
