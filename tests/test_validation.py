import copy
import re
from collections.abc import Callable
from typing import Any

import pytest
from poincare_memory import Ebbinghaus, HalfLife, NoDecay, Product, ValidityWindow
from pydantic import ValidationError

from poincare_orchestra import OBJECTIVES, ControllerPolicy, Scenario, parse_decay

BASE: dict[str, Any] = {
    "name": "mini",
    "title": "Minimal scenario",
    "description": "for validation tests",
    "knowledge": [
        {"id": "root", "text": "Root", "meta": {"domain": "root"}},
        {"id": "leaf", "text": "Leaf", "parent": "root"},
    ],
    "profiles": [{"name": "p", "provider": "provider-a"}],
    "roles": [{"name": "r", "description": "d", "system_prompt": "s", "profile": "p"}],
    "tasks": [{"question": "q?", "expected_facets": ["Leaf"]}],
}


def test_base_is_valid() -> None:
    sc = Scenario.model_validate(BASE)
    assert len(sc.build_memory()) == 2


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["knowledge"].append({"id": "root", "text": "x"}), "knowledge[2] 'root': duplicate id"),
        (
            lambda d: d["knowledge"].insert(0, {"id": "early", "text": "x", "parent": "leaf"}),
            "knowledge[0] 'early': parent 'leaf' is declared later; parents must precede children",
        ),
        (
            lambda d: d["knowledge"].append({"id": "z", "text": "x", "parent": "ghost"}),
            "knowledge[2] 'z': unknown parent 'ghost'",
        ),
        (
            lambda d: d["knowledge"].append({"id": "me", "text": "x", "parent": "me"}),
            "knowledge[2] 'me': an item cannot be its own parent",
        ),
        (lambda d: d["knowledge"].clear(), "knowledge: at least one item is required"),
        (lambda d: d["profiles"].clear(), "profiles: at least one capability profile is required"),
        (lambda d: d["roles"].clear(), "roles: at least one role is required"),
        (
            lambda d: d["profiles"].append({"name": "p", "provider": "provider-b"}),
            "profiles[1] 'p': duplicate profile name",
        ),
        (
            lambda d: d["roles"].append(dict(d["roles"][0])),
            "roles[1] 'r': duplicate role name",
        ),
        (
            lambda d: d["roles"][0].__setitem__("profile", "nope"),
            "roles[0] 'r': unknown profile 'nope'; known profiles: ['p']",
        ),
        (
            lambda d: d["tasks"][0].__setitem__("expected_facets", []),
            "tasks[0] 'q?': expected_facets is empty",
        ),
        (
            lambda d: d["tasks"][0].__setitem__("expected_facets", ["Leaf", " "]),
            "tasks[0] 'q?': expected_facets contains an empty string",
        ),
        (lambda d: d["tasks"][0].__setitem__("question", ""), "at least 1 character"),
        (lambda d: d["knowledge"][0].__setitem__("id", ""), "at least 1 character"),
    ],
)
def test_scenario_validation_messages(mutate: Callable[[dict[str, Any]], Any], message: str) -> None:
    d = copy.deepcopy(BASE)
    mutate(d)
    with pytest.raises(ValidationError, match=re.escape(message)):
        Scenario.model_validate(d)


def test_all_problems_are_reported_together() -> None:
    d = copy.deepcopy(BASE)
    d["knowledge"].append({"id": "root", "text": "x"})
    d["roles"][0]["profile"] = "nope"
    d["tasks"][0]["expected_facets"] = []
    with pytest.raises(ValidationError) as info:
        Scenario.model_validate(d)
    msg = str(info.value)
    assert "duplicate id" in msg and "unknown profile" in msg and "expected_facets is empty" in msg


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("objectives", {"foo": 1.0}, "objectives: unknown objective(s) ['foo']"),
        ("objectives", {"coverage": -0.1}, "objectives: weights must be non-negative, got ['coverage']"),
        ("objectives", {"coverage": 0.0, "cost": 0.0}, "objectives: at least one weight must be positive"),
        ("constraints", {"recall": 0.5}, "constraints: unknown objective(s) ['recall']"),
        (
            "constraints",
            {"coverage": 1.5},
            "constraints: thresholds must lie in [0, 1], got {'coverage': 1.5}",
        ),
        (
            "decay",
            "forever",
            "unknown decay spec 'forever'; expected one of none | half_life | ebbinghaus | validity",
        ),
        ("decay", "half_life:abc", "decay spec 'half_life:abc': 'abc' is not a number of hours"),
        ("decay", "half_life:0", "decay spec 'half_life:0': hours must be positive"),
        ("max_subtasks", 0, "greater than or equal to 1"),
        ("total_budget", 0, "greater than 0"),
        ("retrieval_k", 0, "greater than or equal to 1"),
        ("refine_rounds", -1, "greater than or equal to 0"),
    ],
)
def test_policy_validation_messages(field: str, value: Any, message: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(message)):
        ControllerPolicy(**{field: value})


def test_policy_defaults_name_every_objective() -> None:
    policy = ControllerPolicy()
    assert tuple(policy.objectives) == OBJECTIVES
    assert set(policy.constraints) <= set(OBJECTIVES)


def test_parse_decay() -> None:
    assert isinstance(parse_decay("none"), NoDecay)
    hl = parse_decay("half_life:24")
    assert isinstance(hl, HalfLife) and hl.hours == 24
    assert isinstance(parse_decay("half_life"), HalfLife) and parse_decay("half_life").hours == 720  # type: ignore[attr-defined]
    eb = parse_decay("ebbinghaus")
    assert isinstance(eb, Ebbinghaus) and eb.stability_hours == 168
    assert isinstance(parse_decay("validity"), ValidityWindow)
    prod = parse_decay("half_life:2160+validity")
    assert isinstance(prod, Product) and len(prod.policies) == 2
    assert Scenario.model_validate(BASE).decay_policy().__class__ is HalfLife
