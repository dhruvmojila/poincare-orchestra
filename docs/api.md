# API reference

Everything below is importable from `poincare_orchestra` unless noted. Public API changes are additive and listed in the [changelog](changelog.md).

## Scenario model

::: poincare_orchestra.scenario
    options:
      members:
        - Scenario
        - KnowledgeItem
        - Task
        - ControllerPolicy
        - parse_decay
        - load_scenario
        - list_scenarios
        - OBJECTIVES
        - DECAY_KINDS

## Roles and capability profiles

::: poincare_orchestra.profiles

## Schemas

::: poincare_orchestra.schema

## Controller

::: poincare_orchestra.controller
    options:
      members:
        - analyze
        - decompose
        - InvestmentScheduler
        - QueryAnalysis
        - entity_hits
        - branch_of
        - EPHEMERAL_KINDS

## Ensemble

::: poincare_orchestra.ensemble
    options:
      members:
        - Provider
        - MockProvider
        - LiteLLMProvider
        - ThrottleDetector
        - Router
        - parse_completion
        - looks_like_refusal
        - information_density

## Synthesis

::: poincare_orchestra.synthesis
    options:
      members:
        - synthesize
        - fuse_claims
        - score_objectives
        - weighted_sum
        - agreement
        - compose_answer
        - Objectives

## Orchestrator

::: poincare_orchestra.orchestrator

## Command line

::: poincare_orchestra.cli
    options:
      members:
        - main
        - build_parser
        - configure_logging

## Bundled scenarios

`poincare_orchestra.scenarios.sprint_coaching`, `poincare_orchestra.scenarios.clinical_anatomy` and `poincare_orchestra.scenarios.support_kb` each expose a `SCENARIO` constant (a `Scenario`) built from module-level `KNOWLEDGE`, `PROFILES`, `ROLES` and `TASKS` lists. `load_scenario(name)` returns that constant; the same scenarios are exported as YAML under `scenarios/` in the repository.
