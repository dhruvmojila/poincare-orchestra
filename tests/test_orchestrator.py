import logging

import pytest

from poincare_orchestra import EvalReport, MockProvider, Orchestrator, RunResult, load_scenario


def test_run_survives_a_failing_provider():
    sc = load_scenario("sprint_coaching")
    orch = Orchestrator(
        sc,
        providers=[
            MockProvider("provider-a", fail_after=0, latency_s=0.0),
            MockProvider("provider-b", latency_s=0.0),
        ],
    )
    for task in sc.tasks:
        res = orch.run(task.question)
        assert {r.provider for r in res.responses} == {"provider-b"}
        assert all(not r.refused for r in res.responses)
        assert res.synthesis.claims and res.synthesis.constraints_met
    assert all(e.reasons == ["error: RuntimeError"] for e in orch.router.events)
    assert "error: RuntimeError" in res.explain()


def test_run_survives_every_provider_failing():
    sc = load_scenario("support_kb")
    orch = Orchestrator(
        sc,
        providers=[
            MockProvider("provider-a", fail_after=0, latency_s=0.0),
            MockProvider("provider-b", fail_after=0, latency_s=0.0),
        ],
    )
    res = orch.run(sc.tasks[0].question)
    assert all(r.refused for r in res.responses)
    assert res.synthesis.answer.startswith("No usable responses.")
    assert res.synthesis.uncertainty == 1.0 and not res.synthesis.constraints_met
    assert res.synthesis.objective_scores["coverage"] == 0.0


def test_run_result_json_round_trip():
    sc = load_scenario("support_kb")
    orch = Orchestrator(
        sc,
        providers=[
            MockProvider("provider-a", degrade_after=1, latency_s=0.0, seed=2),
            MockProvider("provider-b", latency_s=0.0),
        ],
    )
    res = orch.run(sc.tasks[1].question)
    text = res.to_json()
    back = RunResult.from_json(text)
    assert back == res
    assert RunResult.model_validate_json(res.model_dump_json()) == res
    assert back.explain() == res.explain()
    compact = res.to_json(indent=None)
    assert "\n" not in compact and RunResult.from_json(compact) == res


def test_eval_report_json():
    sc = load_scenario("clinical_anatomy")
    rep = Orchestrator(
        sc, providers=[MockProvider("provider-a", latency_s=0.0), MockProvider("provider-b", latency_s=0.0)]
    ).evaluate()
    back = EvalReport.model_validate_json(rep.to_json())
    assert back == rep and back.summary() == rep.summary()
    assert 0.0 <= rep.facet_recall <= 1.0 and len(rep.per_task) == len(sc.tasks)


def test_pipeline_stages_are_logged(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="poincare_orchestra")
    sc = load_scenario("support_kb")
    orch = Orchestrator(
        sc,
        providers=[
            MockProvider("provider-a", fail_after=1, latency_s=0.0),
            MockProvider("provider-b", latency_s=0.0),
        ],
    )
    orch.run("Which Kafka version does the connector require now, and why might it fail after an upgrade?")
    text = caplog.text
    for marker in (
        "run: ",
        "analyse: intent=",
        "decompose: ",
        "match q1 -> role=",
        "allocate: ",
        "retrieve q1: ",
        "execute q1 as ",
        "answered q1 via",
        "synthesise: J=",
    ):
        assert marker in text, marker
    assert "raised RuntimeError" in text and "throttling on provider-a (error: RuntimeError)" in text
    assert all(r.name == "poincare_orchestra" for r in caplog.records)


def test_missing_provider_names_are_warned(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.WARNING, logger="poincare_orchestra")
    sc = load_scenario("support_kb")
    orch = Orchestrator(sc, providers=[MockProvider("only-one", latency_s=0.0)])
    assert "expects providers ['provider-a', 'provider-b']" in caplog.text
    res = orch.run(sc.tasks[0].question)
    assert {r.provider for r in res.responses} == {"only-one"}
