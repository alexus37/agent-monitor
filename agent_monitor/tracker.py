"""State tracker — diffs PR states between poll cycles and emits change events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .fetcher import PRStatus


class EventType(Enum):
    COPILOT_STARTED = "copilot_started"
    COPILOT_FINISHED = "copilot_finished"
    DRAFT_TO_READY = "draft_to_ready"
    CHECKS_PASSED = "checks_passed"
    CHECKS_FAILED = "checks_failed"
    LABEL_ADDED = "label_added"
    NEW_PR = "new_pr"
    PR_GONE = "pr_gone"


@dataclass
class ChangeEvent:
    event: EventType
    pr: PRStatus
    detail: str = ""


class StateTracker:
    def __init__(self) -> None:
        self._prev: dict[str, PRStatus] = {}

    def diff(self, current: list[PRStatus]) -> list[ChangeEvent]:
        events: list[ChangeEvent] = []
        current_map = {pr.key: pr for pr in current}

        for pr in current:
            prev = self._prev.get(pr.key)

            if prev is None:
                events.append(ChangeEvent(EventType.NEW_PR, pr))

            else:
                # Copilot agent status changes
                if prev.agent_status != "working" and pr.agent_status == "working":
                    events.append(ChangeEvent(EventType.COPILOT_STARTED, pr))

                if prev.agent_status != "finished" and pr.agent_status == "finished":
                    events.append(ChangeEvent(EventType.COPILOT_FINISHED, pr))

                # Draft → ready
                if prev.is_draft and not pr.is_draft:
                    events.append(ChangeEvent(EventType.DRAFT_TO_READY, pr))

                # CI status changes
                if prev.ci_status != "passed" and pr.ci_status == "passed":
                    events.append(ChangeEvent(EventType.CHECKS_PASSED, pr))

                if prev.ci_status != "failed" and pr.ci_status == "failed":
                    failed_names = [
                        c.name for c in pr.checks
                        if c.conclusion in ("FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED")
                    ]
                    events.append(ChangeEvent(
                        EventType.CHECKS_FAILED, pr,
                        detail=", ".join(failed_names[:3]),
                    ))

        # PRs that disappeared
        for key, prev in self._prev.items():
            if key not in current_map:
                events.append(ChangeEvent(EventType.PR_GONE, prev))

        self._prev = current_map
        return events
