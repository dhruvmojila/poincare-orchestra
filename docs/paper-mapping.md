# Paper mapping

Section-by-section correspondence between D. Mojila, "LLM Orchestration with Geometry-Aware Memory" (IEEE ICBDML 2026, doi:[10.1109/ICBDML68582.2026.11544690](https://doi.org/10.1109/ICBDML68582.2026.11544690)) and this package. Equation numbers are the paper's.

| Paper | What it says | Where it lives here |
|---|---|---|
| §I Introduction, §II Related Work | Motivation and context | [Home](index.md), [FAQ](faq.md) |
| §III-A Geometric Knowledge Representation (eq. 1–3) | Poincaré ball, metric tensor, hyperbolic distance | [`poincare-memory`](https://github.com/dhruvmojila/poincare-memory); used through `Scenario.build_memory()` and `Memory.search(mode="subtree")` |
| §III-B Metacognitive Control Theory (eq. 4) | Control signal `C(t) = F(M(t), G(t), R(t))` | `Orchestrator.run`: state = plan and responses, goal = constraints, resources = `ControllerPolicy.total_budget` |
| §III-B (eq. 5) | Hierarchical decomposition `Q → {q_1, …, q_n}` | `controller.decompose` → `Plan.subtasks` with `depends_on` ([Controller](controller.md#decomposition-eq-5)) |
| §III-C Information-Theoretic Resource Allocation (eq. 6) | `I*(q_i) = argmax_I G(q_i, I) / C(I)` | `InvestmentScheduler.expected_gain`, `.allocate` (skip rule), `.measure_yield`, `.reinvest` ([Controller](controller.md#investment-scheduler-eq-6)) |
| §III-D Multi-Objective Response Optimization (eq. 7) | `max J(R) = Σ w_i f_i(R)` s.t. `f_j(R) ≥ ε_j` | `synthesis.weighted_sum`; weights and thresholds are `ControllerPolicy.objectives` / `.constraints` ([Synthesis](synthesis.md#the-objective-eq-7)) |
| §IV-A Overview | Four components: controller, memory, ensemble, synthesis | `controller.py`, `poincare_memory.Memory`, `ensemble.py`, `synthesis.py`, wired by `orchestrator.py` |
| §IV-B Metacognitive Controller: query analysis and intent recognition | Intent, domain requirements, complexity | `controller.analyze` → `QueryAnalysis` |
| §IV-B: task decomposition | Sub-tasks with dependencies and execution order | `controller.decompose`; the dependency-respecting loop in `Orchestrator.run` |
| §IV-B: capability matching | Static profiles and performance characteristics | `CapabilityProfile.fit`, role selection in `decompose`; dynamic health in `Router` |
| §IV-B: resource allocation ("glycolytic investment cycle") | Invest by expected yield, re-invest | `InvestmentScheduler.allocate` then `.reinvest` in the refinement loop |
| §IV-C Geometry-Aware Memory System | Structured representation, temporal context, retrieval, cross-domain integration | `Scenario.knowledge` → `poincare_memory.Memory` with a decay policy (`ControllerPolicy.decay`); `Orchestrator._context` retrieval order |
| §IV-D Provider-Agnostic LLM Ensemble: capability profiling | Domain expertise, reasoning, creativity, reliability | `CapabilityProfile` fields of the same names |
| §IV-D: throttling detection and mitigation | Response patterns, computation time, information density | `ThrottleDetector` signals: refusal, latency, length, density ([Ensemble](ensemble.md#throttling-detector)) |
| §IV-D: response standardization | One schema for every model output | `schema.AgentResponse`, `schema.Claim` |
| §IV-D: load balancing and failover | Balance across models, fail over on degradation | `Router`: candidate order, cooldown, failover, provider-exception handling |
| §IV-E Response Synthesis: multi-source integration | Fuse partial results | `synthesis.fuse_claims` |
| §IV-E: quality assessment | Multiple quality dimensions | the five objectives in `synthesis.score_objectives` |
| §IV-E: uncertainty quantification | Calibrated uncertainty estimates | `SynthesisResult.uncertainty` (a proxy, see [Synthesis](synthesis.md#uncertainty)) |
| §IV-E: iterative refinement | Re-process when thresholds fail | the refinement loop in `Orchestrator.run` (`refine_rounds`) |
| §V Experimental Evaluation, Table I | Expert-rated accuracy, bits/token, response time, satisfaction | **Not reproduced.** This package reports facet recall and synthesis scores on its own scenarios ([Evaluation](evaluation.md)) |
| §V-E Failure Mode Analysis | What goes wrong and how it is handled | Skipped sub-tasks, refused responses, throttle events and `error: <type>` events are all visible in `RunResult` |
| §VI Discussion, §VII Conclusion | Insights, efficiency, limitations | [FAQ](faq.md) |

## Equations as quoted in the paper

Eq. 5 (hierarchical decomposition):

$$Q \rightarrow \{q_1, q_2, \ldots, q_n\}$$

Eq. 6 (optimal investment per sub-task):

$$I^*(q_i) = \arg\max_{I} \frac{G(q_i, I)}{C(I)}$$

Eq. 7 (weighted sum with epsilon constraints):

$$\max_{R}\; J(R) = \sum_{i=1}^{m} w_i f_i(R) \quad \text{s.t.} \quad f_j(R) \geq \epsilon_j,\ \forall j \in \{1, 2, \ldots, m\}$$

The controller and synthesis pages show how each symbol is instantiated in code.
