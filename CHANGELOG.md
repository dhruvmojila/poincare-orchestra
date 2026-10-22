# Changelog

## [0.1.0] — 2026-10-21
### Fixed
- Sub-tasks carry a `query_text` used for retrieval and gain estimation, so the display-only "(focus: domain)" label no longer shifts the embedding of branch-scoped searches (the clinical-anatomy ACL task went from 0 to full facet recall).

First public release.

### Added
- Scenario model and three bundled scenarios (sprint coaching, clinical anatomy, versioned support KB).
- Scenario files: `Scenario.from_file()` / `Scenario.to_file()` / `Scenario.to_dict()` for JSON (always) and YAML (`pip install 'poincare-orchestra[yaml]'`, with a clear `ImportError` otherwise); `load_scenario()` accepts a bundled name or a file path. The bundled scenarios are exported as `scenarios/*.yaml`, with a hand-written example `scenarios/greenhouse.yaml`.
- Scenario validation with positional error messages: duplicate ids, parents declared after children or unknown, self-parents, duplicate profile/role names, roles referencing unknown profiles, tasks without facets, unknown objective or constraint names, thresholds outside [0, 1], malformed decay specs, empty lists. `parse_decay()`, `OBJECTIVES` and `DECAY_KINDS` are public.
- Metacognitive controller: analysis, decomposition with dependencies, capability matching, investment scheduler with the skip rule and re-investment.
- Ensemble: mock and LiteLLM providers, throttling detector, router with load balancing, cooldown and failover.
  - `Router.call` catches provider exceptions: they become a refused `AgentResponse` (`provider error: ...`) plus a `ThrottleEvent` with reason `error: <type>`, and trigger failover; `Orchestrator.run` never raises on a provider failure.
  - `LiteLLMProvider(timeout_s=...)` passes a per-call timeout to LiteLLM; `parse_completion()` and `looks_like_refusal()` are public and tested without network.
  - `MockProvider(fail_after=N)` simulates an outage.
- Synthesis: claim fusion, five objectives, weighted sum with epsilon constraints, uncertainty, refinement loop.
- `RunResult.to_json()` / `RunResult.from_json()` and `EvalReport.to_json()`.
- Module logger `poincare_orchestra` with INFO messages per pipeline stage (analyse, decompose, allocate, execute, synthesise, refine, eval), DEBUG details and WARNING on provider errors; a `NullHandler` is installed by default.
- CLI: every command accepts a bundled name or a scenario path; new `export` and `validate` commands; `run --json`, `run --fail-after`, `run --model NAME=MODEL`, `run --timeout`, `eval --json`, global `-v`/`-vv`; exit code 1 for invalid scenarios in `validate`, 2 when a scenario cannot be loaded.
- Evaluation harness (facet recall) and documentation site (mkdocs-material) at https://dhruvmojila.github.io/poincare-orchestra, with every code block executed by the test suite.

### Fixed (relative to the pre-release development version)
- `Router.call` raised `AssertionError` when every provider was in cooldown; all providers are now tried, least degraded first.
- A provider in cooldown is skipped for exactly `cooldown_calls` calls (it was `cooldown_calls - 1`).
