"""Auto-labeler — ensures all Copilot PRs have the 'Mark Ready When Ready' label."""

from __future__ import annotations

import subprocess

from .fetcher import PRStatus

LABEL = "Mark Ready When Ready"


def ensure_label(prs: list[PRStatus]) -> list[PRStatus]:
    """Add 'Mark Ready When Ready' label to PRs missing it. Returns list of labeled PRs."""
    labeled: list[PRStatus] = []
    for pr in prs:
        if LABEL not in pr.labels:
            try:
                subprocess.run(
                    ["gh", "pr", "edit", pr.url, "--add-label", LABEL],
                    capture_output=True, text=True, timeout=15,
                )
                pr.labels.append(LABEL)
                labeled.append(pr)
            except Exception:
                pass
    return labeled
