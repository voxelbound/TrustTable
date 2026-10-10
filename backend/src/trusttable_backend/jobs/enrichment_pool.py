"""`EnrichmentPool`: bounded in-process execution of AI enrichment
(`UX-05b`, D-066 item 7).

The model call runs on a worker thread, never inside the request that asked
for it, so start and status are short requests whatever the model's latency.

Two bounds keep a burst of requests from exhausting the model or the process:

- `max_workers` threads run model calls at the same time;
- `max_preparing` is how many enrichments may be `preparing` (running or
  queued) at once. It is enforced by `SqlEnrichmentStore.begin` against the
  stored rows, not by an in-memory counter, so it holds across a restart. Past
  it a start is refused as busy; it is never queued without limit.

A restart loses every in-flight call by design (`ADR-004`: one application
instance). Nothing resurrects them: `main.create_app` fails every row still
`preparing` before this pool accepts work, and a failed enrichment is started
again only by an explicit request.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Final

DEFAULT_ENRICHMENT_WORKERS: Final[int] = 2
DEFAULT_MAX_PREPARING: Final[int] = 8


class EnrichmentPool:
    """Runs AI enrichment work on a bounded background thread pool."""

    def __init__(
        self,
        max_workers: int = DEFAULT_ENRICHMENT_WORKERS,
        max_preparing: int = DEFAULT_MAX_PREPARING,
    ) -> None:
        if max_workers < 1 or max_preparing < 1:
            raise ValueError("an enrichment pool needs at least one worker and one slot")
        self.max_preparing = max_preparing
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="enrichment-worker"
        )

    def submit(self, work: Callable[[], None]) -> Future[None]:
        """Run `work` on a background thread. Production callers ignore the
        returned `Future` (the result lives in the store and is read through
        the status route); tests use it to wait deterministically."""
        return self._executor.submit(work)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)
