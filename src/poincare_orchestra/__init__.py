"""poincare-orchestra: scenario-first reference implementation of LLM orchestration with geometry-aware memory.

Companion to ``poincare-memory``. Implements the metacognitive controller,
provider-agnostic ensemble with throttling detection, and multi-objective
response synthesis described in

    D. Mojila, "LLM Orchestration with Geometry-Aware Memory," IEEE ICBDML 2026,
    doi:10.1109/ICBDML68582.2026.11544690.

Written after the paper from its description; the paper's experimental system
is not part of this package.
"""

import logging

from .controller import InvestmentScheduler, QueryAnalysis, analyze, decompose
from .ensemble import (
    LiteLLMProvider,
    MockProvider,
    Provider,
    Router,
    ThrottleDetector,
    information_density,
    parse_completion,
)
from .orchestrator import EvalReport, Orchestrator
from .profiles import AgentRole, CapabilityProfile
from .scenario import (
    OBJECTIVES,
    ControllerPolicy,
    KnowledgeItem,
    Scenario,
    Task,
    list_scenarios,
    load_scenario,
    parse_decay,
)
from .schema import (
    AgentResponse,
    Claim,
    CompletionRequest,
    Plan,
    RunResult,
    SubTask,
    SynthesisResult,
    ThrottleEvent,
)
from .synthesis import fuse_claims, synthesize, weighted_sum

logging.getLogger("poincare_orchestra").addHandler(logging.NullHandler())

__version__ = "0.1.0"
__all__ = [
    "OBJECTIVES",
    "AgentResponse",
    "AgentRole",
    "CapabilityProfile",
    "Claim",
    "CompletionRequest",
    "ControllerPolicy",
    "EvalReport",
    "InvestmentScheduler",
    "KnowledgeItem",
    "LiteLLMProvider",
    "MockProvider",
    "Orchestrator",
    "Plan",
    "Provider",
    "QueryAnalysis",
    "Router",
    "RunResult",
    "Scenario",
    "SubTask",
    "SynthesisResult",
    "Task",
    "ThrottleDetector",
    "ThrottleEvent",
    "__version__",
    "analyze",
    "decompose",
    "fuse_claims",
    "information_density",
    "list_scenarios",
    "load_scenario",
    "parse_completion",
    "parse_decay",
    "synthesize",
    "weighted_sum",
]
