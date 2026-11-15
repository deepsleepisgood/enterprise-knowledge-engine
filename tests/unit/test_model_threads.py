"""Local model threads follow the container's CPU quota, not the host's CPU count."""

from __future__ import annotations

from app.core import cpu
from app.core.config import get_settings


def _quota_file(tmp_path, text: str) -> str:
    p = tmp_path / "cpu.max"
    p.write_text(text, encoding="ascii")
    return str(p)


def test_cgroup_quota_reads_cpu_max(tmp_path) -> None:
    assert cpu.cgroup_quota(_quota_file(tmp_path, "800000 100000\n")) == 8.0
    assert cpu.cgroup_quota(_quota_file(tmp_path, "max 100000\n")) is None
    assert cpu.cgroup_quota(str(tmp_path / "missing")) is None


def _threads(monkeypatch, quota: float | None, visible: int, setting: str = "0") -> int | None:
    monkeypatch.setenv("MODEL_THREADS", setting)
    monkeypatch.setattr(cpu, "cgroup_quota", lambda: quota)
    monkeypatch.setattr(cpu.os, "cpu_count", lambda: visible)
    get_settings.cache_clear()
    cpu.model_threads.cache_clear()
    try:
        return cpu.model_threads()
    finally:
        get_settings.cache_clear()
        cpu.model_threads.cache_clear()


def test_quota_below_visible_cpus_sets_the_threads(monkeypatch) -> None:
    assert _threads(monkeypatch, quota=8.0, visible=48) == 8
    assert _threads(monkeypatch, quota=0.5, visible=48) == 1


def test_no_quota_keeps_the_runtime_default(monkeypatch) -> None:
    assert _threads(monkeypatch, quota=None, visible=16) is None
    assert _threads(monkeypatch, quota=32.0, visible=16) is None


def test_model_threads_setting_wins(monkeypatch) -> None:
    assert _threads(monkeypatch, quota=8.0, visible=48, setting="6") == 6
