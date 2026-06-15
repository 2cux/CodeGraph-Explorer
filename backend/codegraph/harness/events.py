"""Event bus — lifecycle events with subscribers and JSONL persistence.

Matches PRD Section 26.4.6 EventBus specification.

Event format (matches user specification)::

    {
      "time": "2026-06-15T10:30:12.123456+00:00",
      "type": "run.created",
      "payload": {}
    }

Common events:
- ``run.created``
- ``module.started``
- ``module.finished``
- ``module.failed``
- ``artifact.written``
- ``checkpoint.recorded``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from codegraph.harness.models import EventType, HarnessEvent
from codegraph.harness.utils import timestamp_utc


class EventBus:
    """Synchronous event bus for harness lifecycle events.

    Subscribers register callbacks per event type. Events are emitted
    synchronously and also persisted to ``events.jsonl`` on disk.

    Usage::

        bus = EventBus(store.run_dir(run_id))

        def on_started(event: HarnessEvent) -> None:
            print(f"Run started: {event}")

        bus.subscribe(EventType.RUN_CREATED, on_started)
        bus.emit(EventType.RUN_CREATED, {"run_id": run_id})
    """

    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "events.jsonl"
        self._subscribers: dict[EventType, list[Callable[[HarnessEvent], None]]] = {}

    @property
    def path(self) -> Path:
        """Path to the ``events.jsonl`` file."""
        return self._path

    # ── Subscribe / Unsubscribe ────────────────────────────────────────

    def subscribe(
        self,
        event_type: EventType,
        handler: Callable[[HarnessEvent], None],
    ) -> None:
        """Register a handler for a specific event type.

        Args:
            event_type: The event type to subscribe to.
            handler: Callable that receives the emitted ``HarnessEvent``.
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(
        self,
        event_type: EventType,
        handler: Callable[[HarnessEvent], None],
    ) -> None:
        """Remove a previously registered handler."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h is not handler
            ]

    # ── Emit ───────────────────────────────────────────────────────────

    def emit(
        self,
        event_type: EventType,
        payload: dict[str, Any] | None = None,
    ) -> HarnessEvent:
        """Emit an event: notify subscribers and persist to disk.

        Args:
            event_type: The event type discriminator.
            payload: Optional event-specific data.

        Returns:
            The emitted ``HarnessEvent``.
        """
        event = HarnessEvent(
            time=timestamp_utc(),
            type=event_type,
            payload=payload,
        )

        # Persist to disk
        self._persist(event)

        # Notify subscribers
        handlers = self._subscribers.get(event_type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception:
                # Subscriber errors must not break the event loop.
                pass

        return event

    # ── Persistence ────────────────────────────────────────────────────

    def _persist(self, event: HarnessEvent) -> None:
        """Append event to ``events.jsonl``.

        Uses ``model_dump()`` so new fields added to ``HarnessEvent``
        are automatically included in the serialized output.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # model_dump() produces {"time": ..., "type": ..., "payload": ...}
        # because field names (not aliases) are used for serialization.
        line = json.dumps(
            event.model_dump(mode="json"),
            ensure_ascii=False,
            default=str,
        )
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ── Reading ────────────────────────────────────────────────────────

    def read_events(self) -> list[dict[str, Any]]:
        """Read all events from ``events.jsonl`` as raw dicts.

        Returns events in the order they were recorded (oldest first).
        """
        results: list[dict[str, Any]] = []
        if not self._path.exists():
            return results
        try:
            for line in self._path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        except OSError:
            return results
        return results


# ── Module-level convenience emitters ──────────────────────────────────


def emit_run_created(bus: EventBus, run_id: str) -> HarnessEvent:
    """Emit a ``run.created`` event."""
    return bus.emit(EventType.RUN_CREATED, {"run_id": run_id})


def emit_module_started(bus: EventBus, module_id: str) -> HarnessEvent:
    """Emit a ``module.started`` event."""
    return bus.emit(EventType.MODULE_STARTED, {"module_id": module_id})


def emit_module_finished(
    bus: EventBus,
    module_id: str,
    output: dict[str, Any] | None = None,
) -> HarnessEvent:
    """Emit a ``module.finished`` event."""
    return bus.emit(
        EventType.MODULE_FINISHED, {"module_id": module_id, "output": output}
    )


def emit_module_failed(bus: EventBus, module_id: str, error: str) -> HarnessEvent:
    """Emit a ``module.failed`` event."""
    return bus.emit(EventType.MODULE_FAILED, {"module_id": module_id, "error": error})


def emit_artifact_written(bus: EventBus, artifact_name: str) -> HarnessEvent:
    """Emit an ``artifact.written`` event."""
    return bus.emit(EventType.ARTIFACT_WRITTEN, {"artifact_name": artifact_name})


def emit_checkpoint_recorded(bus: EventBus, checkpoint_name: str) -> HarnessEvent:
    """Emit a ``checkpoint.recorded`` event."""
    return bus.emit(
        EventType.CHECKPOINT_RECORDED, {"checkpoint_name": checkpoint_name}
    )
