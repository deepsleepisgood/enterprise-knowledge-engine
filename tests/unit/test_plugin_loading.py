"""Plug-in modules load once, completely, even when several threads ask at the same moment."""

from __future__ import annotations

import contextlib
import sys
from concurrent.futures import ThreadPoolExecutor

from app.plugins.registry import Plugin


def test_parallel_loads_never_see_a_half_loaded_module(tmp_path) -> None:
    (tmp_path / "calc").mkdir()
    (tmp_path / "calc" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "calc" / "registry.py").write_text(
        "import time\ntime.sleep(0.2)\nCALCULATORS = {'x': 1}\n", encoding="utf-8"
    )
    plugin = Plugin(name="racecheck", path=tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=6) as pool:
            mods = list(pool.map(lambda _: plugin.module("calc.registry"), range(6)))
        assert all(m.CALCULATORS == {"x": 1} for m in mods)
        assert len({id(m) for m in mods}) == 1
    finally:
        for name in [n for n in sys.modules if n.startswith("_plugin_racecheck")]:
            del sys.modules[name]


def test_a_failed_load_is_not_left_behind(tmp_path) -> None:
    (tmp_path / "broken.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    plugin = Plugin(name="brokencheck", path=tmp_path)
    try:
        for _ in range(2):  # the second call runs the module again instead of returning a stub
            with contextlib.suppress(RuntimeError):
                plugin.module("broken")
            assert "_plugin_brokencheck.broken" not in sys.modules
    finally:
        for name in [n for n in sys.modules if n.startswith("_plugin_brokencheck")]:
            del sys.modules[name]
