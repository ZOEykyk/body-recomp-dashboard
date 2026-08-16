from __future__ import annotations

from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
import os
import statistics
from threading import RLock
import time
from typing import Any, Callable, Iterator, TypeVar


PERFORMANCE_SAMPLE_LIMIT = 100
Function = TypeVar("Function", bound=Callable[..., Any])


def performance_debug_enabled() -> bool:
    return str(os.environ.get("BODYOS_PERFORMANCE_DEBUG") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True)
class PerformanceSample:
    operation: str
    elapsed_ms: float
    attributes: dict[str, str | int | float | bool | None]


class PerformanceRecorder:
    """Process-local, bounded timing recorder that never stores payload contents."""

    def __init__(self, sample_limit: int = PERFORMANCE_SAMPLE_LIMIT) -> None:
        self._sample_limit = max(int(sample_limit), 1)
        self._samples: dict[str, deque[PerformanceSample]] = defaultdict(
            lambda: deque(maxlen=self._sample_limit)
        )
        self._lock = RLock()

    def record(
        self,
        operation: str,
        elapsed_ms: float,
        **attributes: str | int | float | bool | None,
    ) -> None:
        safe_attributes = {
            str(key): value
            for key, value in attributes.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        sample = PerformanceSample(
            operation=str(operation),
            elapsed_ms=round(max(float(elapsed_ms), 0.0), 3),
            attributes=safe_attributes,
        )
        with self._lock:
            self._samples[sample.operation].append(sample)

    @contextmanager
    def measure(
        self,
        operation: str,
        **attributes: str | int | float | bool | None,
    ) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.record(operation, (time.perf_counter() - started) * 1000, **attributes)

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        with self._lock:
            return {
                operation: [
                    {
                        "elapsed_ms": sample.elapsed_ms,
                        "attributes": dict(sample.attributes),
                    }
                    for sample in samples
                ]
                for operation, samples in self._samples.items()
            }

    def summary(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = []
            for operation, samples in sorted(self._samples.items()):
                timings = [sample.elapsed_ms for sample in samples]
                if not timings:
                    continue
                rows.append(
                    {
                        "operation": operation,
                        "count": len(timings),
                        "latest_ms": timings[-1],
                        "median_ms": round(statistics.median(timings), 3),
                        "max_ms": round(max(timings), 3),
                    }
                )
            return rows

    def clear(self) -> None:
        with self._lock:
            self._samples.clear()


PERFORMANCE = PerformanceRecorder()


@contextmanager
def measure(
    operation: str,
    **attributes: str | int | float | bool | None,
) -> Iterator[None]:
    with PERFORMANCE.measure(operation, **attributes):
        yield


def instrument(operation: str) -> Callable[[Function], Function]:
    """Measure a callable without recording arguments or return values."""
    def decorator(function: Function) -> Function:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            with measure(operation):
                return function(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator


__all__ = [
    "PERFORMANCE",
    "PerformanceRecorder",
    "PerformanceSample",
    "instrument",
    "measure",
    "performance_debug_enabled",
]
