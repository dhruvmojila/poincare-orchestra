from poincare_orchestra import CapabilityProfile, MockProvider, Router, SubTask, ThrottleDetector
from poincare_orchestra.schema import CompletionRequest


def req(i: int) -> CompletionRequest:
    return CompletionRequest(
        subtask=SubTask(id=f"q{i}", question="what is the rate limit"),
        role_name="tier2",
        system_prompt="x",
        context=[
            "API rate limit is 250 requests per second",
            "burst up to 500 for 10 seconds",
            "tokens expire after 60 minutes",
        ],
        context_ids=["a", "b", "c"],
        context_weights=[1.0, 0.9, 0.8],
        budget=2.0,
    )


def test_detector_flags_degradation_and_router_fails_over():
    bad = MockProvider("provider-a", degrade_after=4, latency_s=0.002, seed=1)
    good = MockProvider("provider-b", latency_s=0.002)
    profiles = [CapabilityProfile(name="p", provider="provider-a")]
    router = Router([bad, good], profiles, detector=ThrottleDetector(min_history=3))
    providers_used = []
    for i in range(12):
        r = router.call(req(i), "p")
        providers_used.append(r.provider)
    assert providers_used[:4] == ["provider-a"] * 4
    assert router.events, "throttling should have been detected"
    assert "provider-b" in providers_used[4:]
    assert any("latency" in x or "length" in x or "refusal" in x for e in router.events for x in e.reasons)


def test_mock_provider_answers_from_context():
    p = MockProvider("x", latency_s=0.0)
    r = p.complete(req(0))
    assert r.claims and r.claims[0].sources == ["a"]
    assert "250 requests" in r.content and not r.refused


def test_provider_exception_becomes_refusal_event_and_failover():
    bad = MockProvider("provider-a", fail_after=0, latency_s=0.0)
    good = MockProvider("provider-b", latency_s=0.0)
    router = Router([bad, good], [CapabilityProfile(name="p", provider="provider-a")])
    r = router.call(req(0), "p")
    assert r.provider == "provider-b" and not r.refused and r.claims
    assert [e.reasons for e in router.events] == [["error: RuntimeError"]]
    assert router.events[0].provider == "provider-a" and router.events[0].tokens == 0
    assert router.degraded == {"provider-a": 3}
    # the failing provider is skipped while it cools down, then retried
    for i in range(1, 4):
        assert router.call(req(i), "p").provider == "provider-b"
    assert bad.calls == 1
    router.call(req(4), "p")
    assert bad.calls == 2 and len(router.events) == 2


def test_all_providers_failing_never_raises():
    router = Router(
        [MockProvider("a", fail_after=0, latency_s=0.0), MockProvider("b", fail_after=0, latency_s=0.0)],
        [],
    )
    for i in range(4):  # every provider stays in cooldown, calls must still be served
        r = router.call(req(i), "p")
        assert r.refused and r.content.startswith("provider error: RuntimeError")
        assert r.meta["throttle"] == ["error: RuntimeError"] and "error" in r.meta
    assert len(router.events) == 8


def test_router_rejects_duplicate_names_and_empty_list():
    import pytest

    with pytest.raises(ValueError, match="unique"):
        Router([MockProvider("a"), MockProvider("a")], [])
    with pytest.raises(ValueError, match="at least one provider"):
        Router([], [])


def test_parse_completion_variants():
    from poincare_orchestra import parse_completion

    answer, claims = parse_completion(
        'Sure.\n```json\n{"answer": "250 rps", "claims": [{"text": "limit 250", "confidence": 0.9, "sources": ["rate_new"]},'
        ' {"confidence": 0.1}, "junk"]}\n```'
    )
    assert (
        answer == "250 rps"
        and [c.text for c in claims] == ["limit 250"]
        and claims[0].sources == ["rate_new"]
    )
    assert parse_completion("plain text answer") == ("plain text answer", [])
    assert parse_completion("{not json}")[1] == []
    assert parse_completion("[1, 2]") == ("[1, 2]", [])


def test_litellm_provider_with_stub(fake_litellm):
    from poincare_orchestra import LiteLLMProvider

    p = LiteLLMProvider("provider-a", "openai/gpt-4o-mini", timeout_s=7.5, api_base="http://localhost:11434")
    r = p.complete(req(0))
    call = fake_litellm.calls[-1]
    assert call["model"] == "openai/gpt-4o-mini" and call["timeout"] == 7.5 and call["api_base"]
    assert call["messages"][0] == {"role": "system", "content": "x"}
    assert "[a] API rate limit is 250 requests per second" in call["messages"][1]["content"]
    assert r.provider == "provider-a" and r.claims[0].sources == ["rate_new"] and r.tokens == 12
    assert r.confidence == 0.9 and not r.refused and r.content.startswith("The current limit")

    fake_litellm.state["reply"] = "I am unable to help with that."
    fake_litellm.state["completion_tokens"] = 0
    r = p.complete(req(1))
    assert r.refused and r.claims == [] and r.confidence == 0.5 and r.tokens == 8  # token count falls back

    no_timeout = LiteLLMProvider("provider-b", "ollama/llama3")
    no_timeout.complete(req(2))
    assert "timeout" not in fake_litellm.calls[-1]


def test_litellm_provider_errors_are_routed_around(fake_litellm):
    from poincare_orchestra import LiteLLMProvider

    fake_litellm.state["raise"] = TimeoutError("read timed out")
    flaky = LiteLLMProvider("provider-a", "openai/gpt-4o-mini", timeout_s=1)
    router = Router(
        [flaky, MockProvider("provider-b", latency_s=0.0)],
        [CapabilityProfile(name="p", provider="provider-a")],
    )
    r = router.call(req(0), "p")
    assert r.provider == "provider-b" and router.events[0].reasons == ["error: TimeoutError"]


def test_litellm_provider_import_error(monkeypatch):
    import sys

    import pytest

    from poincare_orchestra import LiteLLMProvider

    monkeypatch.setitem(sys.modules, "litellm", None)
    with pytest.raises(ImportError, match=r"poincare-orchestra\[litellm\]"):
        LiteLLMProvider("x", "openai/gpt-4o-mini")


def test_litellm_provider_rejects_bad_timeout(fake_litellm):
    import pytest

    from poincare_orchestra import LiteLLMProvider

    with pytest.raises(ValueError, match="timeout_s must be positive"):
        LiteLLMProvider("x", "openai/gpt-4o-mini", timeout_s=0)
