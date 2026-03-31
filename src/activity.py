"""
Activity Log — In-memory ring buffer that captures pipeline events for the dashboard.

Hooks into Python's logging system so all existing logger.info/warning/error calls
from the agents and orchestrator are automatically captured and surfaced in the UI.
"""
from __future__ import annotations

import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from threading import Lock


@dataclass
class ActivityEvent:
    timestamp: float
    level: str
    agent: str
    message: str
    id: int = 0


_AGENT_PATTERN = re.compile(
    r"\[(pipeline|sourcer|analyzer|cover_letter|executor|stealth)\]"
)

_STAGE_PATTERN = re.compile(r"Stage:\s*(\w+)")

_LOGGER_TO_AGENT = {
    "src.agents.sourcer": "sourcer",
    "src.agents.analyzer": "analyzer",
    "src.agents.cover_letter": "cover_letter",
    "src.agents.executor": "executor",
    "src.orchestrator": "pipeline",
    "src.stealth": "stealth",
    "src.main": "scheduler",
}


class ActivityLog:
    """Thread-safe ring buffer of recent activity events."""

    def __init__(self, maxlen: int = 1000):
        self._events: deque[ActivityEvent] = deque(maxlen=maxlen)
        self._lock = Lock()
        self._counter = 0

    def append(self, level: str, agent: str, message: str) -> ActivityEvent:
        with self._lock:
            self._counter += 1
            event = ActivityEvent(
                timestamp=time.time(),
                level=level,
                agent=agent,
                message=message,
                id=self._counter,
            )
            self._events.append(event)
            return event

    def get_events(
        self, since_id: int = 0, limit: int = 200
    ) -> list[dict]:
        with self._lock:
            events = [e for e in self._events if e.id > since_id]
        return [asdict(e) for e in events[-limit:]]

    def get_all(self, limit: int = 200) -> list[dict]:
        with self._lock:
            events = list(self._events)
        return [asdict(e) for e in events[-limit:]]


activity_log = ActivityLog()


class ActivityHandler(logging.Handler):
    """Logging handler that feeds into the activity log."""

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            agent = _LOGGER_TO_AGENT.get(record.name, "")

            if not agent:
                m = _AGENT_PATTERN.search(msg)
                if m:
                    agent = m.group(1)

            if not agent:
                if record.name.startswith("src."):
                    agent = record.name.split(".")[-1]
                else:
                    return

            stage = _STAGE_PATTERN.search(msg)
            if stage:
                agent = "pipeline"

            level = record.levelname.lower()
            if level == "warning":
                level = "warn"

            activity_log.append(level, agent, msg)
        except Exception:
            pass


def install_activity_handler():
    """Attach the ActivityHandler to all relevant loggers."""
    handler = ActivityHandler()
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger_names = [
        "src.agents.sourcer",
        "src.agents.analyzer",
        "src.agents.cover_letter",
        "src.agents.executor",
        "src.orchestrator",
        "src.stealth",
        "src.main",
    ]

    root = logging.getLogger("src")
    root.addHandler(handler)
