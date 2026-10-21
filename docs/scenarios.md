# Scenarios

A scenario is a complete use case as data. The orchestrator never changes; the scenario decides what the memory holds, who answers, what a good answer contains and how much it may cost.

## Anatomy of a scenario

| Field | Type | Role |
|---|---|---|
| `name` | string | identifier; also the default file name for `inspect` |
| `title`, `description` | string | shown by `poincare-orchestra list` |
| `knowledge` | list of `KnowledgeItem` | the hierarchy and dated facts that seed the memory |
| `profiles` | list of `CapabilityProfile` | what each model/provider is good at and what it costs |
| `roles` | list of `AgentRole` | the specialists; each points at a profile |
| `tasks` | list of `Task` | example questions with the facets a good answer must contain |
| `policy` | `ControllerPolicy` | budget, retrieval depth, objective weights, constraints, temporal policy |

A `Scenario` validates itself on construction and when loaded from a file. Problems are reported together with their position: duplicate knowledge ids, a parent declared after its child or not at all, an item that is its own parent, duplicate profile or role names, a role that references an unknown profile, a task without facets or with a blank facet, unknown objective names in the policy, thresholds outside [0, 1], malformed decay specs, and empty `knowledge`, `profiles` or `roles` lists.

## Knowledge: the hierarchy and its dates

| `KnowledgeItem` field | Meaning |
|---|---|
| `id` | unique id; cited by claims and shown in answers |
| `text` | the record. Begin entity records with the entity name and a colon (`"Athlete A: ..."`, `"Ticket 4411: ..."`): the controller recognises a question that names them |
| `parent` | id of the parent record, which must be declared **earlier** in the list. This builds the hierarchy that becomes depth on the Poincaré ball |
| `days_ago` | age of a dated record; undated items are structural knowledge and count as current |
| `valid_from_days_ago`, `valid_until_days_ago` | a validity window, enforced by the `validity` decay kind: superseded facts stop surfacing after their end date |
| `meta` | free dict. Two keys matter: `domain` on a branch (a child of the root) labels the domain the controller reports; `kind` in `event`, `ticket`, `issue`, `case`, `observation` marks a dated, ephemeral record |

Shape the hierarchy as *root → domain branches → facts → dated observations*. The controller maps every retrieved record to its branch, so the branches are the domains it reasons about; the retrieval searches a sub-task's branch first, then the subtrees of the entities the question names, then the whole memory. Records whose time weight has decayed below 0.001 (expired validity windows, very old observations under a short half-life) are not retrieved.

All dates are relative, so a scenario never goes stale: `Scenario.build_memory(now=...)` anchors them (default: the time of the run).

## Roles and capability profiles

| `CapabilityProfile` field | Default | Used for |
|---|---|---|
| `name` | — | referenced by roles |
| `provider` | — | the provider the router prefers for this profile; match it to your provider objects' names |
| `domains` | `[]` | domain labels the model is good at |
| `reasoning`, `creativity`, `reliability` | `0.5` each | intent-dependent fit: planning and comparison weigh `reasoning`, explanation the mean of `reasoning` and `creativity`, factual `reliability` |
| `cost_per_call` | `1.0` | sub-task cost = `cost_per_call × (1 + complexity)` |
| `latency_s` | `1.0` | descriptive (the detector measures real latencies) |

An `AgentRole` has a `name`, a `description`, the `system_prompt` sent to the provider, the `domains` it covers and the `profile` it runs on. Capability matching scores roles by domain overlap plus profile fit ([Controller](controller.md#capability-matching)). Give each domain branch at least one role that lists it.

## Tasks and facets

A `Task` is a `question`, the `expected_facets` (substrings a good answer must contain, case-insensitive) and optional `notes`. Tasks drive `poincare-orchestra eval` and should be answerable from the records: a facet is usually a version number, an id or a technical term that appears in the record you expect to be cited ([Evaluation](evaluation.md#adding-tasks)).

## Policy

| `ControllerPolicy` field | Default | Effect |
|---|---|---|
| `max_subtasks` | `4` | cap on the plan size |
| `total_budget` | `6.0` | the budget split by gain per cost; sub-tasks that do not fit are skipped |
| `min_budget` | `0.5` | floor per kept sub-task (reduced when the budget is small) |
| `retrieval_k` | `5` | base number of records retrieved per sub-task (scaled by its budget, up to 2×) |
| `objectives` | coverage 0.4, density 0.2, agreement 0.1, recency 0.15, cost 0.15 | the weights \(w_i\) of eq. 7 |
| `constraints` | coverage ≥ 0.5, density ≥ 0.2 | the thresholds \(\epsilon_j\) of eq. 7 |
| `refine_rounds` | `1` | refinement rounds allowed while a constraint fails |
| `decay` | `half_life:720` | temporal policy of the memory (below) |

The `decay` spec grammar: `none` · `half_life:<hours>` (default 720 h = 30 days) · `ebbinghaus:<hours>` (stability, default 168 h) · `validity` (validity windows) · any of these joined with `+` for a product, e.g. `half_life:2160+validity`. `parse_decay()` turns a spec into a `poincare_memory` policy.

```python
from poincare_orchestra import ControllerPolicy, parse_decay

print(ControllerPolicy().model_dump())
print(parse_decay("half_life:2160+validity"))
```

## Writing your own scenario in YAML

This is `scenarios/greenhouse.yaml` from the repository, a complete scenario for a small tomato greenhouse. Every feature appears once: a hierarchy with labelled branches, a superseded record hidden by a validity window, dated observations, an entity (`Bay 3`), two profiles on two providers, two roles, two measurable tasks and a policy.

```yaml
--8<-- "scenarios/greenhouse.yaml"
```

Check it, evaluate it and ask it something:

```bash
poincare-orchestra validate scenarios/greenhouse.yaml
poincare-orchestra eval scenarios/greenhouse.yaml
poincare-orchestra run scenarios/greenhouse.yaml "What is the current standard feed?"
```

```text
ok: greenhouse — 16 knowledge items, 2 profiles, 2 roles, 2 tasks, decay=half_life:720+validity
greenhouse: 2 tasks, facet recall 1.00, mean J 0.746, constraints met 100%, throttle events 0
  recall=1.00 J=0.778 subtasks=3 missing=[]  Bay 3 shows whitefly and humid nights; what should we do this week?
  recall=1.00 J=0.713 subtasks=3 missing=[]  What is the current standard feed?
```

The feed question is answered from `feed_new` only: `feed_old` carries `valid_until_days_ago: 60`, so under the `validity` policy its time weight is zero and it is never retrieved.

### The budget decides what gets investigated

The first task touches three branches (climate, scouting, pests), and the two agronomist sub-tasks cost 2.39 each. With `total_budget: 6.0` all three sub-tasks fit (5.77) and the answer includes the `encarsia` record; with `5.0` the pests sub-task is skipped and the Encarsia facet is missed. You can see the skip rule from Python without editing the file:

```python
from poincare_orchestra import Orchestrator, Scenario

scenario = Scenario.from_file("scenarios/greenhouse.yaml")
question = "Bay 3 shows whitefly and humid nights; what should we do this week?"
for budget in (5.0, 6.0):
    policy = scenario.policy.model_copy(update={"total_budget": budget})
    result = Orchestrator(scenario, policy=policy).run(question)
    print(
        budget,
        [(st.id, st.domains[0], st.skipped) for st in result.plan.subtasks],
        "Encarsia" in result.synthesis.answer,
    )
```

```text
5.0 [('q1', 'climate', False), ('q2', 'scouting', False), ('q3', 'pests', True)] False
6.0 [('q1', 'climate', False), ('q2', 'scouting', False), ('q3', 'pests', False)] True
```

### Starting from a bundled scenario

`poincare-orchestra export support_kb -o my_scenario.yaml` writes a bundled scenario as YAML (JSON with a `.json` suffix) with defaults omitted. Edit it, then `validate`, `run` and `eval` it by path. YAML needs `pip install 'poincare-orchestra[yaml]'`; JSON always works.

## Loading and saving from Python

```python
from poincare_orchestra import Scenario, load_scenario

scenario = load_scenario("scenarios/greenhouse.yaml")  # bundled name or path
assert scenario == Scenario.from_file("scenarios/greenhouse.yaml")

path = scenario.to_file("my_copy.json")  # format follows the suffix; format="yaml" overrides
assert Scenario.from_file(path) == scenario
data = scenario.to_dict()  # JSON-compatible dict, defaults and None omitted
assert Scenario.model_validate(data) == scenario
```

A scenario built in Python (as the bundled ones are, see `src/poincare_orchestra/scenarios/support_kb.py`) is passed straight to `Orchestrator(scenario)`.

## The three bundled scenarios

| Scenario | Knowledge (dated) | Profiles / roles / tasks | Policy | Demonstrates |
|---|---|---|---|---|
| `sprint_coaching` | 29 (7) | 2 / 4 / 5 | `total_budget: 8.0`, 30-day half-life | the paper's domain: physiology, biomechanics, strength work and athlete records; planning questions that span several branches; skipped sub-tasks; entity recognition ("Athlete A") |
| `clinical_anatomy` | 24 (3) | 2 / 2 / 4 | `max_subtasks: 3`, `total_budget: 4.0`, `decay: none` | a deep hierarchy (anatomy → system → joint → muscle) driving capability matching between an anatomist and a clinician; a tight budget; the one evaluation miss ([Evaluation](evaluation.md#reading-the-one-miss)) |
| `support_kb` | 22 (10) | 2 / 3 / 4 | `max_subtasks: 3`, `coverage ≥ 0.5`, `decay: half_life:2160+validity` | versioned facts with validity windows: the 2.3 rate limit and Kafka requirement stop surfacing after release 2.4; tickets and issues as ephemeral records; a cheap tier-1 provider beside a tier-2 one |

The counts come from the scenarios themselves:

```python
from poincare_orchestra import list_scenarios, load_scenario

for name in list_scenarios():
    sc = load_scenario(name)
    dated = sum(item.days_ago is not None for item in sc.knowledge)
    print(name, len(sc.knowledge), dated, len(sc.profiles), len(sc.roles), len(sc.tasks))
```

```text
clinical_anatomy 24 3 2 2 4
sprint_coaching 29 7 2 4 5
support_kb 22 10 2 3 4
```

The same three scenarios are exported as `scenarios/sprint_coaching.yaml`, `scenarios/clinical_anatomy.yaml` and `scenarios/support_kb.yaml`; a test asserts that each file loads to exactly the bundled `Scenario`.
