"""Shared fixtures: a stand-in ``litellm`` module so provider code runs without network or credentials."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "scenarios"

JSON_REPLY = (
    '{"answer": "The current limit is 250 requests per second.", '
    '"claims": [{"text": "API rate limit is 250 requests per second", "confidence": 0.9, "sources": ["rate_new"]}]}'
)


@pytest.fixture
def fake_litellm(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Install a fake ``litellm`` whose ``completion`` records its kwargs and returns ``mod.state['reply']``."""
    mod = types.ModuleType("litellm")
    calls: list[dict[str, Any]] = []
    state: dict[str, Any] = {"reply": JSON_REPLY, "raise": None, "completion_tokens": 12}

    def completion(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        if state["raise"] is not None:
            raise state["raise"]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=state["reply"]))],
            usage=SimpleNamespace(completion_tokens=state["completion_tokens"]),
        )

    mod.completion = completion  # type: ignore[attr-defined]
    mod.calls = calls  # type: ignore[attr-defined]
    mod.state = state  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", mod)
    return mod
