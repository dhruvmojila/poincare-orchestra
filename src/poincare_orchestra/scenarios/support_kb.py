"""Scenario: engineering support knowledge base with versioned, time-bounded facts (fictional product)."""

from __future__ import annotations

from ..profiles import AgentRole, CapabilityProfile
from ..scenario import ControllerPolicy, KnowledgeItem, Scenario, Task

K = KnowledgeItem
KNOWLEDGE = [
    K(id="orion", text="Orion data platform support knowledge base", meta={"domain": "product"}),
    K(
        id="api",
        text="Public API: authentication, rate limits and pagination",
        parent="orion",
        meta={"domain": "api"},
    ),
    K(
        id="auth",
        text="API authentication uses short-lived bearer tokens issued by the /token endpoint; tokens expire after 60 minutes",
        parent="api",
    ),
    K(
        id="rate_old",
        text="API rate limit is 100 requests per second per project (release 2.3)",
        parent="api",
        days_ago=90,
        valid_until_days_ago=20,
        meta={"version": "2.3"},
    ),
    K(
        id="rate_new",
        text="API rate limit is 250 requests per second per project since release 2.4; burst up to 500 for 10 seconds",
        parent="api",
        days_ago=20,
        valid_from_days_ago=20,
        meta={"version": "2.4"},
    ),
    K(
        id="pagination",
        text="List endpoints paginate with an opaque cursor; page size maximum is 1000 items",
        parent="api",
    ),
    K(
        id="ingest",
        text="Ingestion: connectors, batching and schema evolution",
        parent="orion",
        meta={"domain": "ingestion"},
    ),
    K(
        id="batch",
        text="Batch ingestion accepts Parquet or CSV up to 5 GB per file; larger files must be split",
        parent="ingest",
    ),
    K(
        id="schema",
        text="Schema evolution: adding nullable columns is automatic; renaming a column requires a migration job",
        parent="ingest",
    ),
    K(
        id="connector_old",
        text="The Kafka connector requires Kafka 2.8 or newer (release 2.3)",
        parent="ingest",
        days_ago=90,
        valid_until_days_ago=20,
        meta={"version": "2.3"},
    ),
    K(
        id="connector_new",
        text="The Kafka connector requires Kafka 3.0 or newer since release 2.4 and supports exactly-once delivery",
        parent="ingest",
        days_ago=20,
        valid_from_days_ago=20,
        meta={"version": "2.4"},
    ),
    K(
        id="storage",
        text="Storage: retention, tiers and encryption",
        parent="orion",
        meta={"domain": "storage"},
    ),
    K(
        id="retention",
        text="Default retention is 30 days in the hot tier and 365 days in the cold tier; retention is configurable per dataset",
        parent="storage",
    ),
    K(
        id="encryption",
        text="All data is encrypted at rest with AES-256; customer-managed keys are available on the enterprise plan",
        parent="storage",
    ),
    K(id="releases", text="Release notes and known issues", parent="orion", meta={"domain": "releases"}),
    K(
        id="rel24",
        text="Release 2.4 (20 days ago): raised API rate limits, Kafka 3.0 connector, exactly-once ingestion",
        parent="releases",
        days_ago=20,
    ),
    K(
        id="issue1",
        text="Known issue in 2.4: cursor pagination returns duplicate items when a dataset is compacted mid-query; fix scheduled for 2.4.1",
        parent="releases",
        days_ago=12,
        meta={"kind": "issue"},
    ),
    K(
        id="rel241",
        text="Release 2.4.1 (3 days ago): fixed duplicate items in cursor pagination during compaction",
        parent="releases",
        days_ago=3,
    ),
    K(id="tickets", text="Recent support tickets", parent="orion", meta={"domain": "tickets"}),
    K(
        id="t1",
        text="Ticket 4411: customer hit 429 responses at 180 requests per second on release 2.3",
        parent="tickets",
        days_ago=35,
        meta={"kind": "ticket"},
    ),
    K(
        id="t2",
        text="Ticket 4502: duplicate rows after compaction while paginating a large dataset",
        parent="tickets",
        days_ago=10,
        meta={"kind": "ticket"},
    ),
    K(
        id="t3",
        text="Ticket 4530: Kafka connector fails to start against Kafka 2.8 after upgrading to 2.4",
        parent="tickets",
        days_ago=6,
        meta={"kind": "ticket"},
    ),
]
PROFILES = [
    CapabilityProfile(
        name="tier2-model",
        provider="provider-a",
        domains=["api", "ingestion", "storage", "releases"],
        reasoning=0.8,
        creativity=0.3,
        reliability=0.9,
        cost_per_call=1.2,
        latency_s=1.2,
    ),
    CapabilityProfile(
        name="tier1-model",
        provider="provider-b",
        domains=["tickets", "product"],
        reasoning=0.5,
        creativity=0.3,
        reliability=0.9,
        cost_per_call=0.4,
        latency_s=0.4,
    ),
]
ROLES = [
    AgentRole(
        name="tier1",
        description="Tier-1 support",
        system_prompt="You are tier-1 support. Answer from current records only; cite record ids and versions.",
        domains=["tickets", "product"],
        profile="tier1-model",
    ),
    AgentRole(
        name="tier2",
        description="Tier-2 engineer",
        system_prompt="You are a tier-2 support engineer. Answer precisely from current records; cite record ids and versions.",
        domains=["api", "ingestion", "storage"],
        profile="tier2-model",
    ),
    AgentRole(
        name="release_engineer",
        description="Release engineer",
        system_prompt="You track releases and known issues; cite record ids.",
        domains=["releases"],
        profile="tier2-model",
    ),
]
TASKS = [
    Task(
        question="What is the current API rate limit per project?",
        expected_facets=["250 requests per second"],
    ),
    Task(
        question="Which Kafka version does the connector require now, and why might it fail after an upgrade?",
        expected_facets=["Kafka 3.0", "4530"],
    ),
    Task(
        question="A customer sees duplicate rows while paginating; is this a known issue and is it fixed?",
        expected_facets=["duplicate", "2.4.1"],
    ),
    Task(question="Explain our encryption and retention defaults.", expected_facets=["AES-256", "30 days"]),
]
SCENARIO = Scenario(
    name="support_kb",
    title="Versioned support knowledge base",
    description="Facts with validity windows: superseded limits and requirements stop surfacing after their release date.",
    knowledge=KNOWLEDGE,
    profiles=PROFILES,
    roles=ROLES,
    tasks=TASKS,
    policy=ControllerPolicy(
        max_subtasks=3, total_budget=6.0, decay="half_life:2160+validity", constraints={"coverage": 0.5}
    ),
)
