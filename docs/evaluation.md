# Evaluation

## The harness

`Orchestrator.evaluate()` runs every `Task` of the scenario through `run()` on the same orchestrator (so the router's history and cooldowns carry over between tasks, as they would in service) and returns an `EvalReport`:

| Field | Meaning |
|---|---|
| `facet_recall` | mean over tasks of *facets found / facets expected*. A facet is found when it occurs, case-insensitively, as a substring of the synthesised answer or of any provider response of that run |
| `mean_weighted_score` | mean of the synthesis objective `J` (eq. 7) over tasks |
| `constraints_met_rate` | share of tasks whose final synthesis satisfied every epsilon constraint |
| `throttle_events` | number of throttle events (including `error: <type>` events) recorded by the router over the whole evaluation |
| `per_task` | per task: `question`, `facet_recall`, `missing` facets, `J`, number of `subtasks` |

Facet recall is deliberately simple: it measures whether the *right records* reached the answer, which is what the controller, the retrieval and the synthesis are responsible for. It does not judge wording, and with mock providers it cannot judge reasoning. It is not the paper's evaluation (expert ratings, bits per token, response time; see [Paper mapping](paper-mapping.md)).

## Running it

```bash
poincare-orchestra eval support_kb
poincare-orchestra eval scenarios/greenhouse.yaml
poincare-orchestra eval sprint_coaching --json
```

or in Python:

```python
from poincare_orchestra import Orchestrator, load_scenario

report = Orchestrator(load_scenario("support_kb")).evaluate()
print(report.summary())
for row in report.per_task:
    print(row["facet_recall"], row["missing"], row["question"])
```

`EvalReport.to_json()` serialises the report; `EvalReport.model_validate_json()` restores it.

## Adding tasks

A task is a question plus the facets a good answer must contain:

```yaml
tasks:
- question: Which Kafka version does the connector require now, and why might it fail after an upgrade?
  expected_facets: [Kafka 3.0, "4530"]
  notes: the second facet is the ticket id that explains the failure
```

Facets should be short, distinctive substrings of the records you expect to be cited (version numbers, ids, technical terms). Validation rejects tasks with no facets or with blank facets, so every task is measurable. In Python, `Task(question=..., expected_facets=[...])` goes in `Scenario.tasks`.

## Current numbers

Produced by `poincare-orchestra eval <scenario>` with this release's code and the default offline providers (`MockProvider`, 10 ms latency), on an idle machine. Mock responses are deterministic; only latencies are measured, and no latency-based throttle event occurred.

| Scenario | Tasks | Facet recall | Mean J | Constraints met | Throttle events |
|---|---|---|---|---|---|
| `sprint_coaching` | 5 | 1.00 | 0.760 | 100% | 0 |
| `clinical_anatomy` | 4 | 1.00 | 0.709 | 100% | 0 |
| `support_kb` | 4 | 1.00 | 0.733 | 100% | 0 |
| `scenarios/greenhouse.yaml` | 2 | 1.00 | 0.746 | 100% | 0 |

```text
$ poincare-orchestra eval sprint_coaching
sprint_coaching: 5 tasks, facet recall 1.00, mean J 0.760, constraints met 100%, throttle events 0
  recall=1.00 J=0.695 subtasks=4 missing=[]  Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks.
  recall=1.00 J=0.813 subtasks=3 missing=[]  Why do hamstring strains happen in late swing, and what reduces the risk?
  recall=1.00 J=0.872 subtasks=2 missing=[]  Is Athlete B ready to resume plyometrics?
  recall=1.00 J=0.756 subtasks=4 missing=[]  Compare the aerobic and glycolytic demands of the 400 m and how to train each.
  recall=1.00 J=0.663 subtasks=4 missing=[]  Athlete A shows forward trunk lean at the end of the race; explain the injury implication and then recommend a drill.

$ poincare-orchestra eval clinical_anatomy
clinical_anatomy: 4 tasks, facet recall 1.00, mean J 0.709, constraints met 100%, throttle events 0
  recall=1.00 J=0.842 subtasks=2 missing=[]  Which rotator cuff muscle is most often torn and why does the patient struggle to start abduction?
  recall=1.00 J=0.646 subtasks=3 missing=[]  Explain the mechanism of ACL injury and the typical presentation.
  recall=1.00 J=0.695 subtasks=3 missing=[]  A newborn holds the arm in waiter's tip posture; which roots are injured?
  recall=1.00 J=0.653 subtasks=3 missing=[]  Compare the territories of the left anterior descending and the right coronary artery.

$ poincare-orchestra eval support_kb
support_kb: 4 tasks, facet recall 1.00, mean J 0.733, constraints met 100%, throttle events 0
  recall=1.00 J=0.812 subtasks=3 missing=[]  What is the current API rate limit per project?
  recall=1.00 J=0.704 subtasks=3 missing=[]  Which Kafka version does the connector require now, and why might it fail after an upgrade?
  recall=1.00 J=0.698 subtasks=3 missing=[]  A customer sees duplicate rows while paginating; is this a known issue and is it fixed?
  recall=1.00 J=0.718 subtasks=3 missing=[]  Explain our encryption and retention defaults.
```

### Why retrieval uses `query_text`

Each sub-task carries two strings: `question`, the labelled form shown in traces (for example with a "(focus: musculoskeletal)" suffix), and `query_text`, the clean question or clause. Branch-scoped retrieval and the gain estimate always embed `query_text`. With a character-n-gram embedder a presentation suffix is enough to reorder a branch's records, and the mock provider only quotes the top of its context, so letting the label leak into the query would cost recall on specific records such as `acl` in `clinical_anatomy`. The rule generalises to any embedder: keep presentation text out of the retrieval query. The embedder itself still matters for ranking, and you can swap it per scenario:

```python
from poincare_memory import HashingEmbedder

from poincare_orchestra import Orchestrator, load_scenario

scenario = load_scenario("clinical_anatomy")
memory = scenario.build_memory(embedder=HashingEmbedder(dim=512))  # any Embedder works here
report = Orchestrator(scenario, memory=memory).evaluate()
print(report.summary())
```

`poincare-memory` also provides `SentenceTransformerEmbedder` for dense embeddings (`pip install 'poincare-memory[embed]'`), which is the realistic choice outside tests.

## Reproducibility

- `MockProvider` output depends only on the request and on its seed (the seed drives the refusal choice when degraded).
- Latencies are real measurements; the detector's `latency` signal fires at 3× the baseline median, which a 10 ms sleep clears comfortably on an idle machine.
- `clock=` on `Orchestrator`/`Scenario.build_memory()` fixes "now" for the relative dates; by default it is the time of the run, and `days_ago` offsets keep every relative age constant, so time weights do not drift between runs.
