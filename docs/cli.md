# Command line

```text
usage: poincare-orchestra [-h] [-v]
                          {list,run,eval,inspect,export,validate} ...

Scenario-first LLM orchestration with geometry-aware memory.

positional arguments:
  {list,run,eval,inspect,export,validate}
    list                list bundled scenarios
    run                 run one question through a scenario (offline mock
                        providers by default)
    eval                run a scenario's bundled tasks and report facet recall
    inspect             write the scenario memory's interactive HTML inspector
    export              write a scenario as a JSON or YAML file (a starting
                        point for your own)
    validate            load a scenario file and report problems

options:
  -h, --help            show this help message and exit
  -v, --verbose         log pipeline stages to stderr (-vv for debug)
```

Every command that takes a `scenario` accepts a **bundled name** (`sprint_coaching`, `clinical_anatomy`, `support_kb`) or the **path** of a `.json`, `.yaml` or `.yml` scenario file. Exit codes: `0` success, `1` when `validate` finds a problem, `2` when a scenario cannot be loaded or a flag is malformed (argparse uses `2` for usage errors too).

## `list`

```bash
poincare-orchestra list
```

```text
clinical_anatomy   Clinical anatomy tutor — Hierarchical anatomy with clinical correlations and recent teaching cases.
sprint_coaching    400 m sprint coaching assistant — Physiology, biomechanics, strength and athlete records; dated observations decay with a 30-day half-life.
support_kb         Versioned support knowledge base — Facts with validity windows: superseded limits and requirements stop surfacing after their release date.
```

## `run`

```text
usage: poincare-orchestra run [-h] [--degrade-after DEGRADE_AFTER]
                              [--fail-after FAIL_AFTER] [--model NAME=MODEL]
                              [--timeout TIMEOUT] [--json]
                              scenario question
```

| Flag | Effect |
|---|---|
| `--degrade-after N` | the first provider (alphabetically) starts returning truncated, slow and sometimes refused answers after `N` calls — exercises the throttling detector |
| `--fail-after N` | the first provider raises `RuntimeError` after `N` calls — exercises error handling and failover |
| `--model NAME=MODEL` | use a real model through LiteLLM for provider `NAME` (repeatable); `NAME` should match a `provider` in the scenario's profiles |
| `--timeout S` | per-call timeout in seconds for `--model` providers (passed to `litellm.completion(timeout=...)`) |
| `--json` | print `RunResult.to_json()` instead of `RunResult.explain()` |

```bash
poincare-orchestra run support_kb "What is the current API rate limit?"
poincare-orchestra run scenarios/greenhouse.yaml "What is the current standard feed?"
poincare-orchestra run support_kb "What is the current API rate limit?" --fail-after 0
poincare-orchestra run sprint_coaching "Athlete A shows forward trunk lean at the end of the race; explain the injury implication and then recommend a drill." --degrade-after 1
poincare-orchestra run support_kb "What is the current API rate limit?" --json
```

With real models (needs `pip install 'poincare-orchestra[litellm]'` and the provider's credentials in the environment; see [Ensemble](ensemble.md#litellmprovider)):

<!-- no-exec -->
```bash
export OPENAI_API_KEY=...
poincare-orchestra run support_kb "What is the current API rate limit?" \
    --model provider-a=openai/gpt-4o-mini --model provider-b=ollama/llama3 --timeout 60
```

## `eval`

```text
usage: poincare-orchestra eval [-h] [--json] scenario
```

Runs the scenario's bundled tasks and prints facet recall, mean `J`, the constraints-met rate and the number of throttle events, then one line per task. `--json` prints the `EvalReport`. Numbers for the bundled scenarios are in [Evaluation](evaluation.md).

```bash
poincare-orchestra eval clinical_anatomy
poincare-orchestra eval scenarios/support_kb.yaml --json
```

## `inspect`

```text
usage: poincare-orchestra inspect [-h] [-o OUT] scenario
```

Writes the scenario memory as `poincare-memory`'s self-contained interactive HTML inspector (Poincaré disk, table and tree). The default file name is `<scenario name>.html`.

```bash
poincare-orchestra inspect sprint_coaching
poincare-orchestra inspect scenarios/greenhouse.yaml -o greenhouse-memory.html
```

## `export`

```text
usage: poincare-orchestra export [-h] [-o OUT] [--format {json,yaml}] scenario
```

Writes a scenario as JSON or YAML. The suffix of `-o` picks the format; without `-o` the scenario is printed to stdout (YAML unless `--format json`). Defaults and `None` fields are omitted, so the file states only what differs from the defaults. This is how the YAML files under `scenarios/` are generated and the quickest way to start your own scenario:

```bash
poincare-orchestra export support_kb -o my_scenario.yaml
poincare-orchestra export clinical_anatomy --format json
```

## `validate`

```text
usage: poincare-orchestra validate [-h] scenario
```

Loads a scenario and reports every problem at once: duplicate ids, parents declared after their children, unknown parents, roles that reference unknown profiles, tasks without facets, unknown objectives or constraints, malformed decay specs. Exit code `1` on problems.

```bash
poincare-orchestra validate scenarios/greenhouse.yaml
```

```text
ok: greenhouse — 16 knowledge items, 2 profiles, 2 roles, 2 tasks, decay=half_life:720+validity
```

A broken file (a role pointing at a profile that does not exist) gives:

```text
invalid: 1 validation error for Scenario
  Value error, roles[0] 'tier1': unknown profile 'ghost'; known profiles: ['tier2-model', 'tier1-model'] [type=value_error, ...]
```

## Logging

`-v` prints INFO lines for each pipeline stage to stderr (`analyse`, `decompose`, `allocate`, `execute`, `synthesise`, `refine`, and `eval` per task); `-vv` adds DEBUG lines (retrieved record ids, role matching scores, per-provider answers). Provider errors are always printed as WARNING lines.

```bash
poincare-orchestra -vv run support_kb "Explain our encryption and retention defaults."
```
