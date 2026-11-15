"""How many CPUs this process may actually use, for sizing the local model runtimes.

In a container the runtime's default thread count is the host's CPU count (48 on a shared host),
not the container's quota (say 8): 48 threads then fight over 8 CPUs, the quota is used up early
in every scheduling period and the whole process (web requests included) is throttled."""

from __future__ import annotations

import math
import os
from functools import lru_cache


def cgroup_quota(path: str = "/sys/fs/cgroup/cpu.max") -> float | None:
    """The container's CPU quota in CPUs (Linux cgroup v2), or None when there is none."""
    try:
        with open(path, encoding="ascii") as f:
            q, period = f.read().split()
        return None if q == "max" else int(q) / int(period)
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=1)
def model_threads() -> int | None:
    """Threads for the embedding and reranker models: MODEL_THREADS when set, else the
    container's quota (rounded down, at least 1) when it is below the CPUs the process sees,
    else None (the runtime's own default)."""
    from app.core.config import get_settings

    if get_settings().model_threads > 0:
        return get_settings().model_threads
    quota = cgroup_quota()
    visible = os.cpu_count() or 1
    if quota is not None and quota < visible:
        return max(1, math.floor(quota))
    return None
