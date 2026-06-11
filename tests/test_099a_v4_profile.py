from dupe_engine.calibration_harness import build_initial_plan


def test_v4_calibration_profile_has_five_focused_runs():
    plan = build_initial_plan("v4_calibration", ["control", "ocr", "vector", "queue"])

    assert len(plan) == 5
    assert [spec.ocr_cap for spec in plan] == [150, 225, 150, 225, 225]
    assert [spec.vector_profile for spec in plan] == [
        "conservative",
        "conservative",
        "conservative",
        "conservative",
        "balanced",
    ]
    assert [spec.post_candidate_rescue_pages for spec in plan] == [0, 0, 50, 25, 0]
    assert all(spec.stage == "v4" for spec in plan)
