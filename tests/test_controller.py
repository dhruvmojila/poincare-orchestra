from poincare_orchestra import InvestmentScheduler, analyze, decompose, load_scenario


def test_analyze_and_decompose_sprint():
    sc = load_scenario("sprint_coaching")
    mem = sc.build_memory()
    a = analyze(
        "Athlete A reports recurring hamstring tightness after 400 m repeats. Plan the next two weeks.", mem
    )
    assert a.intent == "planning"
    assert 0 < a.complexity <= 1
    assert a.domains
    plan = decompose(a, mem, sc.roles, sc.profiles, sc.policy)
    assert 1 <= len(plan.subtasks) <= sc.policy.max_subtasks
    assert all(st.role for st in plan.subtasks)
    alloc = InvestmentScheduler(sc.policy).allocate(plan, mem)
    assert abs(sum(alloc.values()) - sc.policy.total_budget) < 1e-6
    assert all(
        v >= sc.policy.min_budget - 1e-9 or len(plan.subtasks) * sc.policy.min_budget > sc.policy.total_budget
        for v in alloc.values()
    )
    # higher gain per cost receives more budget
    ratios = {st.id: st.expected_gain / st.cost for st in plan.subtasks}
    best = max(ratios, key=ratios.get)
    assert alloc[best] == max(alloc.values())


def test_intents():
    sc = load_scenario("clinical_anatomy")
    mem = sc.build_memory()
    assert analyze("Why does the supraspinatus tear?", mem).intent == "explanation"
    assert analyze("Compare the LAD and the right coronary artery", mem).intent == "comparison"
    assert analyze("Which nerve passes through the carpal tunnel?", mem).intent == "factual"
