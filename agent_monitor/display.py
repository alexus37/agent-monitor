"""Terminal display using rich tables."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .fetcher import PRStatus
from .tracker import ChangeEvent, EventType

console = Console()

_AGENT_STYLE = {
    "working": ("🤖 Working", "blue"),
    "finished": ("✅ Done", "green"),
    "unknown": ("❓ Unknown", "dim"),
}

_CI_STYLE = {
    "passed": ("✅ Passed", "green"),
    "failed": ("❌ Failed", "red"),
    "pending": ("⏳ Pending", "yellow"),
    "unknown": ("❓ Unknown", "dim"),
}

_PR_STATUS_STYLE = {
    "draft": ("📝 Draft", "dim"),
    "open": ("🟢 Open", "cyan"),
    "in_merge_queue": ("🚂 Merging", "magenta"),
    "ready_to_merge": ("🚀 Ready", "green bold"),
}


def render(prs: list[PRStatus], events: list[ChangeEvent]) -> None:
    """Clear screen and render the status table."""
    console.clear()

    now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    console.print(f"[bold]Agent Monitor[/bold]  —  {now}  —  {len(prs)} PR(s)\n")

    if not prs:
        console.print("[dim]No active Copilot PRs found.[/dim]")
        _render_events(events)
        return

    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Repo", style="cyan", no_wrap=True, max_width=30)
    table.add_column("#", style="cyan", justify="right", width=6)
    table.add_column("Title", max_width=50)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Agent", justify="center", width=12)
    table.add_column("CI", justify="center", width=12)
    table.add_column("Review", justify="center", width=12)
    table.add_column("Age", justify="right", width=5)

    for pr in prs:
        agent_text, agent_color = _AGENT_STYLE.get(pr.agent_status, ("?", "dim"))
        ci_text, ci_color = _CI_STYLE.get(pr.ci_status, ("?", "dim"))
        pr_text, pr_color = _PR_STATUS_STYLE.get(pr.pr_status, ("?", "dim"))

        review_map = {
            "APPROVED": ("✅", "green"),
            "CHANGES_REQUESTED": ("🔄", "red"),
            "REVIEW_REQUIRED": ("👀", "yellow"),
        }
        rev_text, rev_color = review_map.get(pr.review_decision, ("—", "dim"))

        table.add_row(
            pr.repo.split("/")[-1],
            str(pr.number),
            Text(pr.title, overflow="ellipsis", no_wrap=True),
            Text(pr_text, style=pr_color),
            Text(agent_text, style=agent_color),
            Text(ci_text, style=ci_color),
            Text(rev_text, style=rev_color),
            pr.age,
        )

    console.print(table)

    # PR links (iTerm2 auto-detects URLs — Cmd+click to open)
    console.print()
    for pr in prs:
        console.print(f"  [dim]#{pr.number}[/dim] {pr.url}")

    # Summary line
    passed = sum(1 for p in prs if p.ci_status == "passed")
    failed = sum(1 for p in prs if p.ci_status == "failed")
    pending = sum(1 for p in prs if p.ci_status == "pending")
    working = sum(1 for p in prs if p.agent_status == "working")
    console.print(
        f"\n[bold]{len(prs)}[/bold] active  "
        f"[green]{passed} passed[/green]  "
        f"[red]{failed} failed[/red]  "
        f"[yellow]{pending} pending[/yellow]  "
        f"[blue]{working} agent working[/blue]"
    )

    _render_events(events)


def _render_events(events: list[ChangeEvent]) -> None:
    if not events:
        return
    console.print("\n[bold]Recent changes:[/bold]")
    for evt in events:
        icon = {
            EventType.COPILOT_STARTED: "🤖",
            EventType.COPILOT_FINISHED: "✅",
            EventType.DRAFT_TO_READY: "🚀",
            EventType.CHECKS_PASSED: "✅",
            EventType.CHECKS_FAILED: "❌",
            EventType.LABEL_ADDED: "🏷️",
            EventType.NEW_PR: "🆕",
            EventType.PR_GONE: "👋",
        }.get(evt.event, "•")
        msg = f"  {icon} {evt.event.value}: {evt.pr.repo}#{evt.pr.number}"
        if evt.detail:
            msg += f" ({evt.detail})"
        console.print(msg)
