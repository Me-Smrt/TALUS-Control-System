from aux_core.reasoning import ReasoningPolicy


def test_simple_explanation_can_remain_fast():
    p = ReasoningPolicy({"default_mode": "auto", "auto_score_threshold": 2.75})
    assert p.choose("Can you explain how a wye-delta transformation works?").mode == "fast"


def test_actual_calculation_problem_can_auto_escalate():
    p = ReasoningPolicy({"default_mode": "auto", "auto_score_threshold": 2.75})
    d = p.choose("Solve this circuit equation carefully and derive the equivalent resistance: $R = (R_1 R_2)/(R_1 + R_2)$. Show your work.")
    assert d.mode == "deep"
