# Agent Monitor

Monitor GitHub Copilot coding agent PRs from the terminal.

## Requirements

- Python 3.9+
- [GitHub CLI (`gh`)](https://cli.github.com/) installed and authenticated
- macOS
- [`terminal-notifier`](https://github.com/julienXX/terminal-notifier) (recommended, for clickable notifications)

## Install

```bash
brew install terminal-notifier  # optional, for click-to-open notifications
cd agent-monitor
pip install -e .
```

## Usage

```bash
# Poll every 60s (default)
agent-monitor

# Custom interval
agent-monitor --interval 30

# Single check, then exit
agent-monitor --once

# Disable macOS notifications
agent-monitor --no-notify

# Custom search query
agent-monitor --query 'is:pr author:app/copilot-swe-agent assignee:octocat state:open'
```

## What it does

1. Finds open PRs created by Copilot agent assigned to you (via GraphQL search)
2. Shows a color-coded table: agent status, CI checks, review state, draft state, clickable titles
3. Auto-applies the "Mark Ready When Ready" label to PRs missing it
4. Sends macOS notifications (click to open the PR in your browser) when:
   - Copilot starts or finishes work (`copilot_work_started`/`copilot_work_finished` timeline events)
   - A PR moves from draft to ready for review
   - CI passes or fails (skipped tests are **not** counted as failures)
