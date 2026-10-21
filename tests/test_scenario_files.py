import json
import sys
from pathlib import Path

import pytest
import yaml

from poincare_orchestra import Scenario, list_scenarios, load_scenario
from tests.conftest import SCENARIO_DIR


@pytest.mark.parametrize("name", list_scenarios())
def test_bundled_yaml_files_round_trip(name: str) -> None:
    path = SCENARIO_DIR / f"{name}.yaml"
    assert path.is_file(), f"run: poincare-orchestra export {name} -o {path}"
    assert Scenario.from_file(path) == load_scenario(name)
    assert load_scenario(path) == load_scenario(name)  # load_scenario accepts paths too
    assert load_scenario(str(path)) == load_scenario(name)


@pytest.mark.parametrize("fmt", ["json", "yaml"])
@pytest.mark.parametrize("name", list_scenarios())
def test_to_file_from_file(tmp_path: Path, name: str, fmt: str) -> None:
    sc = load_scenario(name)
    out = sc.to_file(tmp_path / f"{name}.{fmt}")
    assert out.is_file()
    assert Scenario.from_file(out) == sc
    again = sc.to_file(tmp_path / f"{name}-2.{fmt}")
    assert again.read_text() == out.read_text(), "serialisation is deterministic"
    data = json.loads(out.read_text()) if fmt == "json" else yaml.safe_load(out.read_text())
    assert list(data) == [k for k in Scenario.model_fields if k in data]  # field order preserved
    assert "days_ago" not in data["knowledge"][0]  # None and defaults are omitted


def test_to_dict_omits_defaults_and_none() -> None:
    sc = load_scenario("clinical_anatomy")
    d = sc.to_dict()
    assert d["policy"] == {"max_subtasks": 3, "total_budget": 4.0, "decay": "none"}
    assert all("valid_from_days_ago" not in k for k in d["knowledge"])
    assert Scenario.model_validate(d) == sc


def test_explicit_format_and_yml_suffix(tmp_path: Path) -> None:
    sc = load_scenario("support_kb")
    p = sc.to_file(tmp_path / "scenario.txt", format="yaml")
    assert Scenario.from_file(p, format="yaml") == sc
    assert Scenario.from_file(sc.to_file(tmp_path / "scenario.yml")) == sc
    with pytest.raises(ValueError, match=r"cannot infer the scenario format from 'scenario\.txt'"):
        Scenario.from_file(p)
    with pytest.raises(ValueError, match="cannot infer"):
        sc.to_file(tmp_path / "other.conf")


def test_file_errors(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="scenario file not found"):
        Scenario.from_file(tmp_path / "missing.yaml")
    bad = tmp_path / "list.json"
    bad.write_text("[1, 2]")
    with pytest.raises(ValueError, match="expected a mapping at the top level, got list"):
        Scenario.from_file(bad)


def test_load_scenario_errors(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match=r"unknown scenario 'nope'.*bundled scenarios"):
        load_scenario("nope")
    with pytest.raises(FileNotFoundError, match="scenario file not found"):
        load_scenario(tmp_path / "nope.yaml")


def test_yaml_needs_pyyaml(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "yaml", None)
    sc = load_scenario("support_kb")
    with pytest.raises(ImportError, match=r"poincare-orchestra\[yaml\]"):
        sc.to_file(tmp_path / "x.yaml")
    sc.to_file(tmp_path / "x.json")  # JSON never needs PyYAML
    with pytest.raises(ImportError, match=r"poincare-orchestra\[yaml\]"):
        Scenario.from_file(SCENARIO_DIR / "support_kb.yaml")


@pytest.mark.parametrize("path", sorted(SCENARIO_DIR.glob("*.yaml")), ids=lambda p: p.name)
def test_every_shipped_scenario_file_is_valid(path: Path) -> None:
    sc = Scenario.from_file(path)
    assert sc.name == path.stem
    assert len(sc.build_memory()) == len(sc.knowledge)
