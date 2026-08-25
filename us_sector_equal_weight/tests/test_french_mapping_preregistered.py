"""French mapping must be pre-registered and exclude Telcm/Other."""
from __future__ import annotations

from us_sector_equal_weight.config import FIXED_SECTORS, load_config


def test_french_mapping_covers_nine_and_excludes_telcm_other():
    cfg = load_config()
    m = cfg.french_mapping["etf_to_french_components"]
    assert set(m) == set(FIXED_SECTORS)
    excluded = set(cfg.french_mapping["construction"]["excluded_french_industries"])
    assert excluded == {"Telcm", "Other"}
    for etf, meta in m.items():
        for c in meta["components"]:
            assert c not in excluded
