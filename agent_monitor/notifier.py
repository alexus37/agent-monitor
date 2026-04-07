"""macOS notification dispatch via terminal-notifier.

Clicking a notification opens the PR in the default browser.
Requires: brew install terminal-notifier
Then enable notifications in System Settings > Notifications > terminal-notifier.
"""

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


def notify(event: ChangeEvent) -> None:
    """Send a macOS notification via terminal-notifier. Click to open the PR."""
    title = _TITLES.get(event.event, "Agent Monitor")
    body = f"{event.pr.repo}#{event.pr.number}: {event.pr.title}"
    if event.detail:
        body += f"\n{event.detail}"

    try:
        subprocess.run(
            [
                "terminal-notifier",
                "-title", title,
                "-message", body,
                "-open", event.pr.url,
                "-sound", "Glass",
                "-group", event.pr.key,
                "-sender", "com.apple.Terminal",
            ],
            capture_output=True, timeout=5,
        )
    except FileNotFoundError:
        # Fallback to osascript if terminal-notifier not installed
        script = (
            f'display notification "{_escape(body)}" '
            f'with title "{_escape(title)}" '
            f'sound name "Glass"'
        )
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)
    except Exception:
        pass


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')
