"""Small durable polling loop for Hosted chain reconciliation."""

from __future__ import annotations

import logging
from threading import Event
import time
from typing import Any, Callable

from shared.hosted_facilitator_protocol import HOSTED_CHAIN_PROFILES


class WatcherWorker:
    """Batch execution IDs and isolate one watcher failure from the batch.

    The worker has no signer, broadcaster, Core client, or Redis dependency. It
    only reads IDs from the execution repository and delegates each ID to the
    already fail-closed ``HostedChainWatcher``.
    """

    def __init__(
        self,
        execution_repository: Any,
        watcher: Any,
        *,
        batch_size: int = 100,
        poll_seconds: int = 5,
        stop_event: Event | None = None,
        sleep: Callable[[float], None] = time.sleep,
        logger: Any | None = None,
        resources: tuple[Any, ...] = (),
        chain: str | None = None,
    ) -> None:
        if not callable(getattr(execution_repository, "list_watchable_ids", None)):
            raise ValueError("execution repository is required")
        if not callable(getattr(execution_repository, "record_watcher_attempt", None)):
            raise ValueError("execution repository retry journal is required")
        if not callable(getattr(watcher, "watch", None)):
            raise ValueError("chain watcher is required")
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise ValueError("watch batch size is unsafe")
        if type(poll_seconds) is not int or not 0 <= poll_seconds <= 3600:
            raise ValueError("watch poll interval is unsafe")
        if not callable(sleep):
            raise ValueError("watch sleep function is required")
        if logger is not None and not callable(getattr(logger, "warning", None)):
            raise ValueError("watch logger is invalid")
        watcher_chain = getattr(watcher, "chain", None)
        selected_chain = chain if chain is not None else watcher_chain
        if selected_chain not in HOSTED_CHAIN_PROFILES:
            raise ValueError("watch chain is required and unsupported")
        if watcher_chain is not None and watcher_chain != selected_chain:
            raise ValueError("watch chain does not match watcher instance")
        self._repository = execution_repository
        self._watcher = watcher
        self._chain = selected_chain
        self._batch_size = batch_size
        self._poll_seconds = poll_seconds
        self._stop_event = stop_event or Event()
        self._sleep = sleep
        self._logger = logger or logging.getLogger(__name__)
        self._resources = tuple(resources)
        self._cursor: str | None = None

    @property
    def cursor(self) -> str | None:
        return self._cursor

    @property
    def stop_event(self) -> Event:
        return self._stop_event

    @property
    def chain(self) -> str:
        return self._chain

    def stop(self) -> None:
        self._stop_event.set()

    def close(self) -> None:
        for resource in reversed(self._resources):
            close = getattr(resource, "close", None)
            if callable(close):
                try:
                    close()
                    continue
                except Exception:
                    continue
            engine = getattr(resource, "engine", None)
            dispose = getattr(engine, "dispose", None)
            if callable(dispose):
                try:
                    dispose()
                except Exception:
                    pass

    def run_once(self) -> list[Any]:
        if self._stop_event.is_set():
            return []
        execution_ids = self._repository.list_watchable_ids(
            # The durable attempt timestamp, rather than UUID ordering, is the
            # retry cursor. A failed UUID must be moved behind untouched work.
            chain=self._chain,
            after_execution_id=None,
            limit=self._batch_size,
        )
        if not isinstance(execution_ids, list):
            raise RuntimeError("watcher repository returned invalid IDs")
        if not execution_ids:
            self._cursor = None
            return []

        results: list[Any] = []
        for execution_id in execution_ids:
            if self._stop_event.is_set():
                break
            if not isinstance(execution_id, str) or not execution_id:
                continue
            try:
                self._repository.record_watcher_attempt(execution_id)
            except Exception:
                try:
                    self._logger.warning(
                        "watcher_attempt_record_failed",
                        extra={
                            "execution_id": execution_id,
                            "error_code": "watch_retry_unavailable",
                        },
                    )
                except Exception:
                    pass
                continue
            try:
                result = self._watcher.watch(execution_id)
            except Exception:
                # The next ID must still be attempted. The durable watcher and
                # repository decide the economic outcome; this loop never
                # fabricates a result from an exception.
                try:
                    self._logger.warning(
                        "watcher_item_failed",
                        extra={
                            "execution_id": execution_id,
                            "error_code": "watch_failed",
                        },
                    )
                except Exception:
                    pass
                result = None
            if result is not None:
                results.append(result)
            self._cursor = execution_id
        return results

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            self.run_once()
            if not self._stop_event.is_set():
                self._sleep(self._poll_seconds)


HostedWatcherWorker = WatcherWorker
