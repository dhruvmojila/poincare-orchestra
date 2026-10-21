import pytest

from poincare_orchestra import MockProvider, Orchestrator, list_scenarios, load_scenario


@pytest.mark.parametrize("name", list_scenarios())
def test_scenario_builds_and_evaluates(name):
    sc = load_scenario(name)
    mem = sc.build_memory()
    assert len(mem) == len(sc.knowledge)
    orch = Orchestrator(
        sc, providers=[MockProvider(n, latency_s=0.0) for n in sorted({p.provider for p in sc.profiles})]
    )
    rep = orch.evaluate()
    assert rep.tasks == len(sc.tasks)
    assert rep.facet_recall >= 0.6, rep.per_task
    assert rep.constraints_met_rate >= 0.5
    text = orch.run(sc.tasks[0].question).explain()
    assert "Answer:" in text and "allocate" not in text  # explain prints the plan and answer


def test_validity_windows_hide_superseded_facts():
    sc = load_scenario("support_kb")
    orch = Orchestrator(
        sc, providers=[MockProvider("provider-a", latency_s=0.0), MockProvider("provider-b", latency_s=0.0)]
    )
    res = orch.run("What is the current API rate limit per project?")
    assert "250 requests per second" in res.synthesis.answer
    assert "rate_old" not in res.synthesis.answer


def test_throttling_is_routed_around_in_a_run():
    sc = load_scenario("sprint_coaching")
    orch = Orchestrator(
        sc,
        providers=[
            MockProvider("provider-a", degrade_after=2, latency_s=0.002, seed=3),
            MockProvider("provider-b", latency_s=0.002),
        ],
    )
    results = [orch.run(t.question) for t in sc.tasks] + [orch.run(t.question) for t in sc.tasks]
    assert any(resp.provider == "provider-a" for r in results for resp in r.responses)
    assert any(r.throttle_events for r in results)
    assert any(resp.provider == "provider-b" for r in results for resp in r.responses)
