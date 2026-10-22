# poincare-orchestra

[![Docs](https://img.shields.io/badge/docs-dhruvmojila.github.io%2Fpoincare--orchestra-indigo)](https://dhruvmojila.github.io/poincare-orchestra)
[![Paper](https://img.shields.io/badge/DOI-10.1109%2FICBDML68582.2026.11544690-blue)](https://doi.org/10.1109/ICBDML68582.2026.11544690)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.23551737.svg)](https://doi.org/10.5281/zenodo.23551737)
[![License](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)

**Scenario-first LLM orchestration with geometry-aware memory.** Companion to [`poincare-memory`](https://github.com/dhruvmojila/poincare-memory) and the official open-source reference implementation of the controller, ensemble and synthesis components of

> D. Mojila, "LLM Orchestration with Geometry-Aware Memory," *2026 2nd International Conference on Big Data & Machine Learning (ICBDML)*, Bhopal, India, Feb. 2026, pp. 1–7. doi:[10.1109/ICBDML68582.2026.11544690](https://doi.org/10.1109/ICBDML68582.2026.11544690)

> **Provenance.** Written after the paper from its description. The system used for the paper's experiments is not released; every number this package reports is produced by the code here.

**Documentation:** <https://dhruvmojila.github.io/poincare-orchestra> — getting started, scenarios, the controller / ensemble / synthesis components with the paper's equations, evaluation numbers, CLI and API reference.

## Why scenario-first

A use case is data, not code. A **scenario** bundles the domain hierarchy and dated facts that seed the memory, the specialist roles and their capability profiles, example tasks with the facets a good answer must cover, and the controller policy. The orchestrator is the same for all of them; a new use case is a new scenario file (JSON or YAML). Three ship with the package:

| Scenario | What it shows |
|---|---|
| `sprint_coaching` | the paper's domain: physiology, biomechanics, strength work and athlete records with a 30-day half-life on observations |
| `clinical_anatomy` | an anatomy tutor whose hierarchy drives capability matching between an anatomist and a clinician |
| `support_kb` | a versioned knowledge base where superseded limits carry validity windows and stop surfacing after a release |

The same three are exported as YAML under [`scenarios/`](scenarios/), next to a fully annotated hand-written example, [`scenarios/greenhouse.yaml`](scenarios/greenhouse.yaml).

Everything runs **offline** with deterministic mock providers, so the control loop is inspectable and testable; plug in any real model through LiteLLM.

```bash
pip install 'poincare-orchestra[yaml]'       # pulls poincare-memory; [yaml] adds YAML scenario files
poincare-orchestra list
poincare-orchestra run sprint_coaching "Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks."
poincare-orchestra run sprint_coaching "Athlete A shows forward trunk lean at the end of the race; explain the injury implication and then recommend a drill." --degrade-after 1   # throttling detected and routed around
poincare-orchestra run support_kb "What is the current API rate limit?" --fail-after 0    # a provider outage becomes an `error: RuntimeError` event, not a crash
poincare-orchestra eval clinical_anatomy
poincare-orchestra validate scenarios/greenhouse.yaml
poincare-orchestra run scenarios/greenhouse.yaml "What is the current standard feed?"       # any command takes a bundled name or a file path
poincare-orchestra inspect sprint_coaching      # the scenario memory as an interactive Poincaré disk
```

## What a run does (paper §IV)

1. **Analyse** the query: intent, complexity and the memory branches it touches (the hierarchy is the domain model).
2. **Decompose** it into sub-tasks along its clauses and branches, with dependencies (eq. 5), and **match** each to a role by domain overlap and capability profile.
3. **Allocate** budget by expected information gain per cost (eq. 6): gain = relevance of what the memory holds × novelty against the other sub-tasks; sub-tasks that do not fit are skipped; after execution, yield is measured as distinct claims per token and the remainder is re-invested in the weakest sub-tasks.
4. **Execute** through a provider-agnostic router: capability-profiled providers, load balancing, a throttling detector that compares each response to the provider's own baseline (latency, length, information density, refusals), failover with cooldown, and provider exceptions converted into refused responses plus `error: <type>` events.
5. **Synthesise**: fuse near-duplicate claims across sources, score coverage / density / agreement / recency / cost, apply the weighted-sum objective with epsilon constraints (eq. 7), derive uncertainty from claim confidence and refusals, and refine while constraints fail and budget remains.

`RunResult.explain()` prints the whole trace; `RunResult.to_json()` serialises it (and `RunResult.from_json()` restores it). Every stage logs to the `poincare_orchestra` logger (`-v` / `-vv` on the CLI).

## Real models

<!-- no-exec -->
```python
from poincare_orchestra import LiteLLMProvider, Orchestrator, load_scenario

sc = load_scenario("support_kb")
orch = Orchestrator(
    sc,
    providers=[
        LiteLLMProvider("provider-a", "openai/gpt-4o-mini", timeout_s=60),
        LiteLLMProvider("provider-b", "ollama/llama3"),
    ],
)
print(orch.run("What is the current API rate limit?").explain())
```

Provider names map to the `provider` field of each scenario's capability profiles. On the command line: `poincare-orchestra run support_kb "..." --model provider-a=openai/gpt-4o-mini --model provider-b=ollama/llama3 --timeout 60` (`pip install 'poincare-orchestra[litellm]'`).

## Writing a scenario

Start from a bundled one — `poincare-orchestra export support_kb -o mine.yaml` — or from [`scenarios/greenhouse.yaml`](scenarios/greenhouse.yaml). List `knowledge` items (`parent` builds the hierarchy; `days_ago`, `valid_from_days_ago`, `valid_until_days_ago` give time), `profiles`, `roles`, `tasks` with `expected_facets`, and a `policy`. Then `poincare-orchestra validate mine.yaml` reports every inconsistency at once (duplicate ids, parents after children, unknown profiles, tasks without facets, bad decay specs…), and `run` / `eval` / `inspect` accept the path. In Python: `Scenario.from_file(path)`, `Scenario.to_file(path)`, or build a `Scenario` object and pass it to `Orchestrator`. The [Scenarios](https://dhruvmojila.github.io/poincare-orchestra/scenarios/) page documents every field.

## Development

```bash
uv venv && uv pip install -e ".[dev]"
pytest && ruff check . && ruff format --check . && mypy && mkdocs build --strict
```

The test suite executes every Python code block and every `poincare-orchestra` command in the documentation.

## Citing

Cite the paper (BibTeX in `CITATION.cff`). The software itself is archived on Zenodo under the concept DOI [10.5281/zenodo.23551737](https://doi.org/10.5281/zenodo.23551737), which always resolves to the latest release. Licence: Apache-2.0. © 2026 Dhruv Mojila.
