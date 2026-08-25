from statistical_signal_validation.registry import count_trials, load_registry


def test_registry_includes_failures_and_ew9_labels():
    reg = load_registry()
    info = count_trials(reg)
    assert info["n_trials_total"] >= 20
    assert "us_sector_equal_weight" in info["by_project"]
    assert info["ew9_classification"]["EW9_monthly"] == "DISCOVERY_ONLY"
    assert info["ew9_classification"]["EW9_quarterly"] == "PRE_REGISTERED_SECONDARY"
    ids = {t["id"] for t in info["rows"]}
    assert "ew9_monthly" in ids
    assert "sm_base_12_1_top3" in ids  # failed sector momentum counted
