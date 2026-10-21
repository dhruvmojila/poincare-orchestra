import json

import yaml

from poincare_orchestra import EvalReport, RunResult, Scenario, load_scenario
from poincare_orchestra.cli import main
from tests.conftest import SCENARIO_DIR

KB_YAML = SCENARIO_DIR / "support_kb.yaml"


def test_cli(tmp_path, capsys):
    assert main(["list"]) == 0
    assert main(["run", "support_kb", "What is the current API rate limit?"]) == 0
    assert main(["run", "sprint_coaching", "Plan hamstring work for Athlete A", "--degrade-after", "1"]) == 0
    assert main(["eval", "clinical_anatomy"]) == 0
    assert main(["inspect", "support_kb", "-o", str(tmp_path / "kb.html")]) == 0
    out = capsys.readouterr().out
    assert "sprint_coaching" in out and "250" in out and (tmp_path / "kb.html").exists()


def test_cli_accepts_scenario_paths(tmp_path, capsys, monkeypatch):
    assert main(["run", str(KB_YAML), "What is the current API rate limit?"]) == 0
    assert "250 requests per second" in capsys.readouterr().out
    assert main(["eval", str(KB_YAML)]) == 0
    assert capsys.readouterr().out.startswith("support_kb: 4 tasks")
    monkeypatch.chdir(tmp_path)
    assert main(["inspect", str(KB_YAML)]) == 0
    assert (tmp_path / "support_kb.html").exists()  # default name comes from the scenario, not the path
    assert capsys.readouterr().out == "wrote support_kb.html\n"
    assert main(["validate", str(KB_YAML)]) == 0
    assert capsys.readouterr().out.startswith(
        "ok: support_kb — 22 knowledge items, 2 profiles, 3 roles, 4 tasks"
    )
    assert main(["validate", "sprint_coaching"]) == 0


def test_cli_json_outputs(capsys):
    assert main(["run", "support_kb", "What is the current API rate limit?", "--json"]) == 0
    res = RunResult.from_json(capsys.readouterr().out)
    assert res.question == "What is the current API rate limit?" and res.responses
    assert main(["eval", "support_kb", "--json"]) == 0
    rep = EvalReport.model_validate_json(capsys.readouterr().out)
    assert rep.scenario == "support_kb" and rep.tasks == 4


def test_cli_export(tmp_path, capsys):
    out = tmp_path / "anatomy.json"
    assert main(["export", "clinical_anatomy", "-o", str(out)]) == 0
    assert capsys.readouterr().out == f"wrote {out}\n"
    assert Scenario.from_file(out) == load_scenario("clinical_anatomy")
    assert main(["export", "clinical_anatomy"]) == 0  # YAML to stdout
    assert Scenario.model_validate(yaml.safe_load(capsys.readouterr().out)) == load_scenario(
        "clinical_anatomy"
    )
    assert main(["export", str(KB_YAML), "--format", "json"]) == 0
    assert Scenario.model_validate(json.loads(capsys.readouterr().out)) == load_scenario("support_kb")
    assert main(["export", "sprint_coaching", "-o", str(tmp_path / "sprint.txt"), "--format", "yaml"]) == 0
    assert Scenario.from_file(tmp_path / "sprint.txt", format="yaml") == load_scenario("sprint_coaching")


def test_cli_errors(tmp_path, capsys):
    assert main(["run", "nope", "q"]) == 2
    assert "error: unknown scenario 'nope'" in capsys.readouterr().err
    assert main(["eval", str(tmp_path / "missing.yaml")]) == 2
    assert "scenario file not found" in capsys.readouterr().err
    bad = tmp_path / "bad.yaml"
    data = load_scenario("support_kb").to_dict()
    data["roles"][0]["profile"] = "ghost"
    bad.write_text(yaml.safe_dump(data, sort_keys=False))
    assert main(["validate", str(bad)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("invalid:") and "roles[0] 'tier1': unknown profile 'ghost'" in err
    assert main(["run", str(bad), "q"]) == 2
    assert main(["run", "support_kb", "q", "--model", "no-equals-sign"]) == 2
    assert "--model expects NAME=MODEL" in capsys.readouterr().err
    assert main(["export", "support_kb", "-o", str(tmp_path / "x.conf")]) == 2
    assert "cannot infer the scenario format" in capsys.readouterr().err


def test_cli_fail_after_and_verbose(capsys):
    assert main(["-vv", "run", "support_kb", "What is the current API rate limit?", "--fail-after", "0"]) == 0
    captured = capsys.readouterr()
    assert "!! throttling on provider-a: error: RuntimeError" in captured.out
    assert "WARNING provider provider-a raised RuntimeError" in captured.err
    assert "INFO analyse: intent=" in captured.err and "DEBUG retrieve q1:" in captured.err
    assert main(["run", "support_kb", "What is the current API rate limit?"]) == 0
    assert "INFO" not in capsys.readouterr().err  # back to warnings only


def test_cli_real_models_through_stub(fake_litellm, capsys):
    assert (
        main(
            [
                "run",
                "support_kb",
                "What is the current API rate limit?",
                "--model",
                "provider-a=openai/gpt-4o-mini",
                "--model",
                "provider-b=ollama/llama3",
                "--timeout",
                "30",
            ]
        )
        == 0
    )
    assert fake_litellm.calls and all(c["timeout"] == 30.0 for c in fake_litellm.calls)
    assert {c["model"] for c in fake_litellm.calls} <= {"openai/gpt-4o-mini", "ollama/llama3"}
    assert "250 requests per second" in capsys.readouterr().out
