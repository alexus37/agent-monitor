"""CLI entry point — argparse + main polling loop."""

from __future__ import annotations

import argparse
import sys
import time

from . import fetcher, labeler, tracker, notifier, display
from .tracker import EventType

DEFAULT_QUERY = "is:pr author:app/copilot-swe-agent assignee:@me state:open archived:false"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="agent-monitor",
        description="Monitor GitHub Copilot coding agent PRs from the terminal.",
    )
    p.add_argument("--interval", type=int, default=60, help="Polling interval in seconds (default: 60)")
    p.add_argument("--once", action="store_true", help="Fetch once and exit")
    p.add_argument("--no-notify", action="store_true", help="Disable macOS notifications")
    p.add_argument("--query", type=str, default=DEFAULT_QUERY, help="Override search query")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    state = tracker.StateTracker()

    try:
        while True:
            try:
                prs = fetcher.fetch_prs(args.query)
            except Exception as e:
                display.console.print(f"[red]Error fetching PRs: {e}[/red]")
                if args.once:
                    sys.exit(1)
                time.sleep(args.interval)
                continue

            # Auto-label
            newly_labeled = labeler.ensure_label(prs)

            # Diff state
            events = state.diff(prs)

            # Add label events
            for pr in newly_labeled:
                events.append(tracker.ChangeEvent(EventType.LABEL_ADDED, pr, detail="Mark Ready When Ready"))

            # Notify
            if not args.no_notify:
                for evt in events:
                    notifier.notify(evt)

            # Display
            display.render(prs, events)

            if args.once:
                break

            _countdown(args.interval)

    except KeyboardInterrupt:
        display.console.print("\n[dim]Stopped.[/dim]")


def _countdown(seconds: int) -> None:
    from rich.live import Live
    from rich.text import Text

    with Live(Text(""), console=display.console, refresh_per_second=1) as live:
        for remaining in range(seconds, 0, -1):
            live.update(Text(f"\nNext poll in {remaining}s — Ctrl+C to quit", style="dim"))
            time.sleep(1)


if __name__ == "__main__":
    main()
