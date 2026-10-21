# poincare-orchestra

**Scenario-first LLM orchestration with geometry-aware memory.** `poincare-orchestra` is the open-source reference implementation of the *controller*, *ensemble* and *synthesis* components of

> D. Mojila, "LLM Orchestration with Geometry-Aware Memory," *2026 2nd International Conference on Big Data & Machine Learning (ICBDML)*, Bhopal, India, Feb. 2026, pp. 1–7. doi:[10.1109/ICBDML68582.2026.11544690](https://doi.org/10.1109/ICBDML68582.2026.11544690)

It runs on top of [`poincare-memory`](https://github.com/dhruvmojila/poincare-memory), which implements the paper's memory component: a hierarchy-aware, time-aware store on the Poincaré ball.

> **Provenance.** Written after the paper from its description. The system used for the paper's experiments is not released; every number this package reports is produced by the code here.

## What it is

A use case is **data, not code**. A *scenario* bundles the domain hierarchy and dated facts that seed the memory, the specialist roles and their capability profiles, example tasks with the facets a good answer must cover, and the controller policy. The orchestrator is the same for every scenario; a new use case is a new JSON or YAML file. Three scenarios ship with the package, and everything runs **offline** with deterministic mock providers, so the control loop is inspectable and testable. Any real model can be plugged in through LiteLLM.

## Who it is for

- **Readers of the paper** who want to see the control loop of §III–§IV as small, rule-based, traceable steps rather than prose: each equation maps to a named function (see [Paper mapping](paper-mapping.md)).
- **Engineers** who need a transparent orchestration harness: deterministic providers for tests, a throttling detector and failover that can be exercised without a network, and a JSON trace of every run.
- **Students and teachers** who want to write a scenario for their own domain in an afternoon ([Scenarios](scenarios.md)).

## The eight steps of a run

`Orchestrator.run(question)` **analyses** the question (intent, complexity, the memory branches and named entities it touches), **decomposes** it into sub-tasks along its clauses and branches with dependencies (eq. 5), **matches** each sub-task to a role by domain overlap and capability profile, **allocates** the budget by expected information gain per cost and skips what does not fit (eq. 6), **retrieves** hierarchy-aware context for each sub-task from the Poincaré memory (branch first, then named entities, then global), **executes** the sub-tasks through a provider-agnostic router whose throttling detector compares each response with the provider's own baseline and fails over with a cooldown, **synthesises** the responses by fusing near-duplicate claims and scoring coverage, density, agreement, recency and cost under the weighted-sum objective with epsilon constraints (eq. 7), and **refines** by re-investing the remaining budget in the weakest sub-tasks while a constraint fails. `RunResult.explain()` prints the whole trace; `RunResult.to_json()` serialises it.

## Quick start

```bash
pip install 'poincare-orchestra[yaml]'
poincare-orchestra list
poincare-orchestra run sprint_coaching "Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks."
poincare-orchestra eval support_kb
```

Continue with [Getting started](getting-started.md) for a line-by-line reading of the output.

## Citing

Please cite the paper (BibTeX in the repository's `CITATION.cff`):

```text
D. Mojila, "LLM Orchestration with Geometry-Aware Memory," 2026 2nd International Conference on
Big Data & Machine Learning (ICBDML), Bhopal, India, 2026, pp. 1-7,
doi: 10.1109/ICBDML68582.2026.11544690.
```

Licence: Apache-2.0. © 2026 Dhruv Mojila.
