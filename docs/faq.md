# FAQ

## Is this the paper's experimental system?

No. It is a **reference implementation** written after the paper from its description. The system used for the experiments in §V of the paper is not released, and this package does not reproduce Table I of the paper. Every number in this documentation comes from running this code on the bundled scenarios ([Evaluation](evaluation.md)).

## Where do the equations come from?

From the paper: eq. 5 (decomposition), eq. 6 (investment) and eq. 7 (weighted sum with epsilon constraints) are quoted in [Paper mapping](paper-mapping.md). The *instantiation* of their symbols (what counts as information gain, how coverage is measured) is this package's choice and is documented on the [Controller](controller.md) and [Synthesis](synthesis.md) pages.

## Why are the mock providers so simple?

So that the control loop can be observed in isolation. `MockProvider` answers from the retrieved context deterministically, can be told to degrade (truncation, slowness, refusals) or to fail after N calls, and runs in milliseconds. Capability matching, budget allocation, throttling detection, failover, synthesis and refinement all run exactly as they would with real models.

## Can I use real models?

Yes, through LiteLLM: `pip install 'poincare-orchestra[litellm]'`, then pass `LiteLLMProvider` instances or use `poincare-orchestra run ... --model provider-a=openai/gpt-4o-mini`. Provider names should match the `provider` field of the scenario's capability profiles. See [Ensemble](ensemble.md#litellmprovider).

## Why did a sub-task get `SKIPPED (budget)`?

The investment scheduler keeps sub-tasks in order of expected gain per cost while their summed cost fits `policy.total_budget` (the first one is always kept). The rest are skipped rather than under-funded, and they are listed as "Open sub-questions" in the answer. Raise `total_budget`, lower `max_subtasks`, or give the roles cheaper profiles. Details in [Controller](controller.md#investment-scheduler-eq-6).

## What happens when a provider fails or times out?

`Router.call` catches the exception, records a refused `AgentResponse` whose content starts with `provider error:`, appends a `ThrottleEvent` with reason `error: <ExceptionType>`, puts the provider in cooldown and tries the next candidate. `Orchestrator.run` therefore never raises because of a provider; if every provider fails, the run completes with refused responses and `uncertainty = 1.0`.

## Why is facet recall on `clinical_anatomy` not 1.0?

All bundled tasks score full facet recall with the offline mock providers; the numbers are reported as measured in [Evaluation](evaluation.md), which also explains why retrieval embeds the clean `query_text` rather than the labelled sub-task.

## Does it need a GPU or network access?

No. The default embedder is `poincare_memory.HashingEmbedder` (pure NumPy), the default providers are offline mocks, and the test suite runs without network. Real models need whatever LiteLLM needs for the chosen provider.

## Is the retrieval really hyperbolic?

The memory is `poincare_memory.Memory`: every record is a point in the Poincaré ball, with depth from its level in the hierarchy you declare with `parent`. This package uses its `subtree` searches (a sub-task's branch, then the entities the question names), its time weights (decay policies and validity windows) and its `inspect()` visualiser. The geometry itself is documented in `poincare-memory`.

## How do I write a scenario for my domain?

Export a bundled one as a starting point (`poincare-orchestra export support_kb -o mine.yaml`), edit it, `poincare-orchestra validate mine.yaml`, then `run` and `eval` it. A complete annotated example is in [Scenarios](scenarios.md#writing-your-own-scenario-in-yaml).

## Can I replace the rule-based controller with an LLM planner?

Yes. `decompose` returns a `Plan`; anything that produces a `Plan` with `SubTask`s (ids, questions, domains, `branch_id`, `depends_on`) can replace it, and the scheduler, router and synthesis keep working unchanged.

## Why do results vary slightly between runs?

Mock responses are deterministic, but latencies are measured with a real clock. The throttling detector compares latencies with a median, so on a heavily loaded machine a spurious `latency` event is possible; the bundled evaluations report `throttle events 0` on an idle machine.

## How should I cite it?

Cite the paper (see [Home](index.md#citing)). The software metadata is in `CITATION.cff` and `.zenodo.json` in the repository.
