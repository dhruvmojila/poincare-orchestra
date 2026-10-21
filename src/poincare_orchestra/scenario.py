"""Scenario model: a use case is data, not code.

A scenario bundles the domain hierarchy and dated facts that seed the memory,
the specialist roles and their capability profiles, example tasks with the
facets a good answer must cover, and the controller policy. Everything the
orchestrator does is driven by it, so a new use case is a new scenario file
(JSON or YAML; see :meth:`Scenario.from_file`).
"""

from __future__ import annotations

import importlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from poincare_memory import DecayPolicy, Ebbinghaus, HalfLife, Memory, NoDecay, Product, ValidityWindow
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from .profiles import AgentRole, CapabilityProfile

logger = logging.getLogger("poincare_orchestra")

OBJECTIVES: tuple[str, ...] = ("coverage", "density", "agreement", "recency", "cost")
"""The five synthesis objectives a policy may weight or constrain."""

DECAY_KINDS: tuple[str, ...] = ("none", "half_life", "ebbinghaus", "validity")
"""Accepted kinds in a ``ControllerPolicy.decay`` spec."""

FileFormat = Literal["json", "yaml"]
_SUFFIXES: dict[str, FileFormat] = {".json": "json", ".yaml": "yaml", ".yml": "yaml"}


def parse_decay(spec: str) -> DecayPolicy:
    """Build a ``poincare_memory`` decay policy from a spec string.

    Grammar: ``none`` | ``half_life:<hours>`` | ``ebbinghaus:<hours>`` | ``validity``,
    and any of these joined with ``+`` for a product (for example
    ``half_life:2160+validity``). Hours default to 720 (half-life) and 168
    (Ebbinghaus stability) when omitted.

    Raises:
        ValueError: if a kind is unknown or an hour value is not a positive number.
    """
    policies: list[DecayPolicy] = []
    for part in spec.split("+"):
        kind, _, arg = part.strip().partition(":")
        if kind not in DECAY_KINDS:
            raise ValueError(
                f"unknown decay spec {part!r}; expected one of {' | '.join(DECAY_KINDS)}"
                " (hours after ':'), joined with '+'"
            )
        hours: float | None = None
        if arg:
            try:
                hours = float(arg)
            except ValueError:
                raise ValueError(f"decay spec {part!r}: {arg!r} is not a number of hours") from None
            if hours <= 0:
                raise ValueError(f"decay spec {part!r}: hours must be positive")
        if kind == "none":
            policies.append(NoDecay())
        elif kind == "half_life":
            policies.append(HalfLife(hours=hours if hours is not None else 720.0))
        elif kind == "ebbinghaus":
            policies.append(Ebbinghaus(stability_hours=hours if hours is not None else 168.0))
        else:
            policies.append(ValidityWindow())
    return policies[0] if len(policies) == 1 else Product(*policies)


class KnowledgeItem(BaseModel):
    """One record of the scenario memory.

    ``parent`` builds the hierarchy (parents must be listed before their
    children); ``days_ago`` dates a record relative to the run; the two
    ``valid_*`` fields give it a validity window for the ``validity`` decay kind.
    """

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    parent: str | None = None
    days_ago: float | None = None
    """Age of a dated record; undated items are structural knowledge and count as current."""
    meta: dict[str, Any] = Field(default_factory=dict)
    valid_from_days_ago: float | None = None
    valid_until_days_ago: float | None = None


class Task(BaseModel):
    """An example question with the facets (substrings) a good answer must contain."""

    question: str = Field(min_length=1)
    expected_facets: list[str] = Field(
        default_factory=list, description="substrings a good answer must contain"
    )
    notes: str = ""


class ControllerPolicy(BaseModel):
    """Budget, retrieval, objective weights, epsilon constraints and temporal policy of a scenario."""

    max_subtasks: int = Field(default=4, ge=1)
    total_budget: float = Field(default=6.0, gt=0)
    min_budget: float = Field(default=0.5, ge=0)
    retrieval_k: int = Field(default=5, ge=1)
    objectives: dict[str, float] = Field(
        default_factory=lambda: {
            "coverage": 0.4,
            "density": 0.2,
            "agreement": 0.1,
            "recency": 0.15,
            "cost": 0.15,
        }
    )
    """Weights ``w_i`` of eq. 7; keys must be objective names."""
    constraints: dict[str, float] = Field(default_factory=lambda: {"coverage": 0.5, "density": 0.2})
    """Epsilon thresholds ``ε_j`` of eq. 7 in [0, 1]; keys must be objective names."""
    refine_rounds: int = Field(default=1, ge=0)
    decay: str = "half_life:720"
    """``none`` | ``half_life:<hours>`` | ``ebbinghaus:<hours>`` | ``validity`` | ``half_life:<h>+validity``"""

    @field_validator("objectives", "constraints")
    @classmethod
    def _known_objectives(cls, value: dict[str, float], info: ValidationInfo) -> dict[str, float]:
        unknown = [k for k in value if k not in OBJECTIVES]
        if unknown:
            raise ValueError(f"{info.field_name}: unknown objective(s) {unknown}; known: {list(OBJECTIVES)}")
        if info.field_name == "objectives":
            negative = [k for k, v in value.items() if v < 0]
            if negative:
                raise ValueError(f"objectives: weights must be non-negative, got {negative}")
            if value and sum(value.values()) <= 0:
                raise ValueError("objectives: at least one weight must be positive")
        else:
            bad = {k: v for k, v in value.items() if not 0.0 <= v <= 1.0}
            if bad:
                raise ValueError(f"constraints: thresholds must lie in [0, 1], got {bad}")
        return value

    @field_validator("decay")
    @classmethod
    def _valid_decay(cls, value: str) -> str:
        parse_decay(value)
        return value


class Scenario(BaseModel):
    """A complete use case: memory contents, roles, capability profiles, tasks and policy.

    Validation runs on construction and on :meth:`from_file`: duplicate ids,
    parents declared after their children, roles that reference unknown
    profiles and tasks without facets are reported with their position.
    """

    name: str = Field(min_length=1)
    title: str
    description: str
    knowledge: list[KnowledgeItem]
    profiles: list[CapabilityProfile]
    roles: list[AgentRole]
    tasks: list[Task]
    policy: ControllerPolicy = Field(default_factory=ControllerPolicy)

    @model_validator(mode="after")
    def _consistent(self) -> Scenario:
        problems: list[str] = []
        if not self.knowledge:
            problems.append("knowledge: at least one item is required")
        if not self.profiles:
            problems.append("profiles: at least one capability profile is required")
        if not self.roles:
            problems.append("roles: at least one role is required")
        seen: set[str] = set()
        all_ids = {item.id for item in self.knowledge}
        for i, item in enumerate(self.knowledge):
            where = f"knowledge[{i}] {item.id!r}"
            if item.id in seen:
                problems.append(f"{where}: duplicate id")
            if item.parent is not None and item.parent not in seen:
                if item.parent == item.id:
                    problems.append(f"{where}: an item cannot be its own parent")
                elif item.parent in all_ids:
                    problems.append(
                        f"{where}: parent {item.parent!r} is declared later; parents must precede children"
                    )
                else:
                    problems.append(f"{where}: unknown parent {item.parent!r}")
            seen.add(item.id)
        profile_names: list[str] = []
        for i, prof in enumerate(self.profiles):
            if prof.name in profile_names:
                problems.append(f"profiles[{i}] {prof.name!r}: duplicate profile name")
            profile_names.append(prof.name)
        role_names: list[str] = []
        for i, role in enumerate(self.roles):
            if role.name in role_names:
                problems.append(f"roles[{i}] {role.name!r}: duplicate role name")
            role_names.append(role.name)
            if role.profile not in profile_names:
                problems.append(
                    f"roles[{i}] {role.name!r}: unknown profile {role.profile!r}; known profiles: {profile_names}"
                )
        for i, task in enumerate(self.tasks):
            if not task.expected_facets:
                problems.append(f"tasks[{i}] {task.question[:40]!r}: expected_facets is empty")
            elif any(not f.strip() for f in task.expected_facets):
                problems.append(
                    f"tasks[{i}] {task.question[:40]!r}: expected_facets contains an empty string"
                )
        if problems:
            raise ValueError("; ".join(problems))
        return self

    # ------------------------------------------------------------------ memory
    def decay_policy(self) -> DecayPolicy:
        """The ``poincare_memory`` decay policy described by ``policy.decay``."""
        return parse_decay(self.policy.decay)

    def build_memory(
        self, now: datetime | None = None, clock: Callable[[], datetime] | None = None, **kwargs: Any
    ) -> Memory:
        """Seed a fresh :class:`poincare_memory.Memory` with the knowledge items.

        ``now`` anchors the relative dates (default: the current UTC time);
        ``clock`` overrides the memory's clock; other keyword arguments go to
        ``Memory`` (for example ``embedder=``).
        """
        now = now or datetime.now(timezone.utc)
        mem = Memory(decay=self.decay_policy(), clock=clock or (lambda: now), **kwargs)
        for item in self.knowledge:
            t = now - timedelta(days=item.days_ago) if item.days_ago is not None else now
            vf = (
                now - timedelta(days=item.valid_from_days_ago)
                if item.valid_from_days_ago is not None
                else None
            )
            vu = (
                now - timedelta(days=item.valid_until_days_ago)
                if item.valid_until_days_ago is not None
                else None
            )
            mem.add(
                item.text, parent=item.parent, id=item.id, t=t, meta=item.meta, valid_from=vf, valid_until=vu
            )
        logger.debug(
            "built memory for scenario %s: %d records, decay=%s", self.name, len(mem), self.policy.decay
        )
        return mem

    def role(self, name: str) -> AgentRole:
        for r in self.roles:
            if r.name == name:
                return r
        raise KeyError(name)

    def profile(self, name: str) -> CapabilityProfile:
        for p in self.profiles:
            if p.name == name:
                return p
        raise KeyError(name)

    # ------------------------------------------------------------------- files
    def to_dict(self) -> dict[str, Any]:
        """JSON-compatible dict with defaults and ``None`` fields omitted (the on-disk form)."""
        return self.model_dump(mode="json", exclude_defaults=True, exclude_none=True)

    def to_file(self, path: str | Path, format: FileFormat | None = None) -> Path:
        """Write the scenario as JSON or YAML; the format follows the suffix unless given.

        YAML needs PyYAML (``pip install 'poincare-orchestra[yaml]'``).
        """
        path = Path(path)
        fmt = format or _format_of(path)
        data = self.to_dict()
        if fmt == "json":
            text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        else:
            text = _yaml().safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
        path.write_text(text, encoding="utf-8")
        logger.info("wrote scenario %s to %s (%s)", self.name, path, fmt)
        return path

    @classmethod
    def from_file(cls, path: str | Path, format: FileFormat | None = None) -> Scenario:
        """Load and validate a scenario from a JSON or YAML file.

        Raises:
            FileNotFoundError: if ``path`` does not exist.
            ValueError: if the suffix is not ``.json``/``.yaml``/``.yml`` and no ``format`` is given,
                or if the file is not a mapping.
            pydantic.ValidationError: if the contents are inconsistent (see the class docstring).
            ImportError: for YAML without PyYAML installed.
        """
        path = Path(path)
        if not path.is_file():
            raise FileNotFoundError(f"scenario file not found: {path}")
        fmt = format or _format_of(path)
        text = path.read_text(encoding="utf-8")
        data = json.loads(text) if fmt == "json" else _yaml().safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a mapping at the top level, got {type(data).__name__}")
        scenario = cls.model_validate(data)
        logger.info("loaded scenario %s from %s", scenario.name, path)
        return scenario


def _format_of(path: Path) -> FileFormat:
    try:
        return _SUFFIXES[path.suffix.lower()]
    except KeyError:
        raise ValueError(
            f"cannot infer the scenario format from {path.name!r}; use a .json/.yaml/.yml suffix or pass format="
        ) from None


def _yaml() -> Any:
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            "YAML scenarios need PyYAML: pip install 'poincare-orchestra[yaml]' (or pip install pyyaml)"
        ) from exc
    return yaml


SCENARIO_MODULES: dict[str, str] = {
    "sprint_coaching": "poincare_orchestra.scenarios.sprint_coaching",
    "clinical_anatomy": "poincare_orchestra.scenarios.clinical_anatomy",
    "support_kb": "poincare_orchestra.scenarios.support_kb",
}


def load_scenario(name: str | Path) -> Scenario:
    """A bundled scenario by name, or any scenario file by path (``.json``, ``.yaml``, ``.yml``).

    Raises:
        KeyError: if ``name`` is neither a bundled scenario nor an existing file.
        FileNotFoundError: if ``name`` looks like a scenario file but does not exist.
    """
    spec = str(name)
    if spec in SCENARIO_MODULES:
        module = importlib.import_module(SCENARIO_MODULES[spec])
        scenario: Scenario = module.SCENARIO
        logger.debug("loaded bundled scenario %s", spec)
        return scenario
    path = Path(name)
    if path.is_file():
        return Scenario.from_file(path)
    if path.suffix.lower() in _SUFFIXES:
        raise FileNotFoundError(f"scenario file not found: {path}")
    raise KeyError(
        f"unknown scenario {spec!r}; bundled scenarios: {sorted(SCENARIO_MODULES)}; "
        "or pass the path to a .json/.yaml scenario file"
    )


def list_scenarios() -> list[str]:
    """Names of the bundled scenarios."""
    return sorted(SCENARIO_MODULES)
