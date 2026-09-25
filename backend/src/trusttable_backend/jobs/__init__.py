"""Bounded in-process background execution (`JOB-01`, `WP-075`).

`JobPool` is the sole public surface: a thin, `Settings.background_worker_
count`-bounded `concurrent.futures.ThreadPoolExecutor` wrapper that runs
`analysis.service.run_analysis` on a background thread and mediates
cooperative cancellation. See `pool.py`'s own docstring for detail.
"""

from __future__ import annotations

from .pool import JobPool

__all__ = ["JobPool"]
