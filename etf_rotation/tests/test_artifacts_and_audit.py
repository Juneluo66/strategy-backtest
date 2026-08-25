from __future__ import annotations

from dataclasses import replace

from etf_rotation.artifacts import config_hash
from etf_rotation.audit import data_audit
from etf_rotation.config import frozen_config


def test_config_hash_changes_when_frozen_runtime_changes(tmp_path) -> None:
    base = replace(frozen_config(lookback=20), cache_dir=tmp_path / "cache", reports_dir=tmp_path / "reports")
    changed = replace(base, frequency=3)
    assert config_hash(base) != config_hash(changed)


def test_data_audit_marks_missing_cache_as_failed(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("etf_rotation.audit._names", dict)
    config = replace(frozen_config(lookback=20), cache_dir=tmp_path / "cache", reports_dir=tmp_path / "reports")
    detail, coverage, partial = data_audit(config)
    assert len(detail) == 49
    assert not detail["audit_pass"].any()
    assert coverage["missing_trading_days"].notna().all()
    assert partial["status"].eq("partial_unavailable").all()
