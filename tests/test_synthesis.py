from poincare_orchestra import AgentResponse, Claim, Plan, SubTask, fuse_claims, synthesize, weighted_sum


def resp(sid, provider, texts, srcs):
    return AgentResponse(
        subtask_id=sid,
        role="r",
        provider=provider,
        content=" ".join(texts),
        claims=[Claim(text=t, confidence=0.7, sources=[s]) for t, s in zip(texts, srcs, strict=True)],
        sources=srcs,
        tokens=40,
    )


def test_fuse_dedupes_and_weighted_sum_constraints():
    rs = [
        resp("q1", "a", ["rate limit is 250 per second", "tokens expire after 60 minutes"], ["x", "y"]),
        resp("q2", "b", ["rate limit is 250 per second", "page size maximum is 1000"], ["x", "z"]),
    ]
    claims = fuse_claims(rs)
    assert len(claims) == 3
    merged = next(c for c in claims if "250" in c.text)
    assert merged.sources == ["x"]
    j, ok, violated = weighted_sum(
        {"coverage": 1.0, "agreement": 0.1}, {"coverage": 0.5, "agreement": 0.5}, {"agreement": 0.2}
    )
    assert not ok and violated == ["agreement"] and abs(j - 0.55) < 1e-9
    plan = Plan(
        query="q",
        intent="factual",
        complexity=0.2,
        subtasks=[SubTask(id="q1", question="a"), SubTask(id="q2", question="b")],
    )
    res = synthesize(
        plan,
        rs,
        {"x": 1.0, "y": 0.5, "z": 0.25},
        {"coverage": 0.5, "agreement": 0.5},
        {"coverage": 0.5},
        spent=2.0,
        budget=4.0,
    )
    assert res.objective_scores["coverage"] == 1.0 and res.constraints_met
    assert "250" in res.answer
