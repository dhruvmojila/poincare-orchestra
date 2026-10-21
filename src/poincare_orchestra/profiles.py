"""Capability profiles and agent roles (paper §IV-B capability matching, §IV-D capability profiling)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CapabilityProfile(BaseModel):
    """Static description of what a model/provider is good at and what it costs."""

    name: str
    provider: str
    domains: list[str] = Field(default_factory=list)
    reasoning: float = 0.5
    creativity: float = 0.5
    reliability: float = 0.5
    cost_per_call: float = 1.0
    latency_s: float = 1.0

    def fit(self, domains: list[str], intent: str) -> float:
        """Capability-matching score in [0, 1] for a sub-task with these domains and intent."""
        overlap = len(set(d.lower() for d in domains) & set(d.lower() for d in self.domains))
        domain_score = overlap / max(1, len(domains)) if domains else 0.5
        intent_w = {
            "planning": self.reasoning,
            "explanation": 0.5 * self.reasoning + 0.5 * self.creativity,
            "comparison": self.reasoning,
            "factual": self.reliability,
        }.get(intent, 0.5)
        return 0.6 * domain_score + 0.4 * intent_w


class AgentRole(BaseModel):
    name: str
    description: str
    system_prompt: str
    domains: list[str] = Field(default_factory=list)
    profile: str
