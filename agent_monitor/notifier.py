"""macOS notification dispatch — shows notification, opens PR for important events."""

from __future__ import annotations

import subprocess

from .tracker import ChangeEvent, EventType

_TITLES = {
    EventType.COPILOT_STARTED: "🤖 Copilot Started",
    EventType.COPILOT_FINISHED: "✅ Copilot Finished",
    EventType.DRAFT_TO_READY: "🚀 PR Ready for Review",
    EventType.CHECKS_PASSED: "✅ CI Passed",
    EventType.CHECKS_FAILED: "❌ CI Failed",
    EventType.LABEL_ADDED: "🏷️ Label Added",
    EventType.NEW_PR: "🆕 New Copilot PR",
    EventType.PR_GONE: "👋 PR Closed/Merged",
}

# Events important enough to auto-open the PR in the browser
_AUTO_OPEN_EVENTS = {
    EventType.COPILOT_FINISHED,
    EventType.CHECKS_FAILED,
    EventType.DRAFT_TO_READY,
}


def notify(event: ChangeEvent) -> None:
    """Send a macOS notification and auto-open important PRs in the browser."""
    title = _TITLES.get(event.event, "Agent Monitor")
    body = f"{event.pr.repo}#{event.pr.number}: {event.pr.title}"
    if event.detail:
        body += f"\n{event.detail}"

    script = (
        f'display notification "{_escape(body)}" '
        f'with title "{_escape(title)}" '
        f'sound name "Glass"'
    )
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass

    # Auto-open PR in browser for important events
    if event.event in _AUTO_OPEN_EVENTS:
        try:
            subprocess.run(["open", event.pr.url], capture_output=True, timeout=5)
        except Exception:
            pass


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
