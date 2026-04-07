# Agent Monitor

Monitor GitHub Copilot coding agent PRs from the terminal.

## Requirements

- Python 3.9+
- [GitHub CLI (`gh`)](https://cli.github.com/) installed and authenticated
- macOS
- [`terminal-notifier`](https://github.com/julienXX/terminal-notifier) for notifications

## Install

```bash
# Install terminal-notifier
brew install terminal-notifier

# Enable notifications: System Settings → Notifications → terminal-notifier → Allow Notifications

# Install agent-monitor
cd agent-monitor
pip install -e .
```

> **Important:** After installing `terminal-notifier`, you must enable notifications for it in
> **System Settings → Notifications → terminal-notifier** and set alert style to **Alerts** or **Banners**.
> Without this, notifications will be silently dropped.

## Usage

```bash
# Poll every 60s (default)
agent-monitor

# Custom interval
agent-monitor --interval 30

# Single check, then exit
agent-monitor --once

# Disable notifications
agent-monitor --no-notify

# Custom search query
agent-monitor --query 'is:pr author:app/copilot-swe-agent assignee:octocat state:open'
```

## What it does

1. Finds open PRs created by Copilot agent assigned to you (via GraphQL search)
2. Shows a color-coded table: PR status, agent status, CI checks, review state
3. Auto-applies the "Mark Ready When Ready" label to PRs missing it
4. Sends notifications (click to open the PR in your browser) when:
   - Copilot starts or finishes work
   - A PR moves from draft to ready for review
   - CI passes or fails (skipped tests are **not** counted as failures)
