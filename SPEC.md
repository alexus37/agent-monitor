# Agent Monitor — Design Specification

A Python CLI tool that monitors GitHub Copilot coding agent work from the terminal.

---

## Problem

When you assign GitHub Copilot to issues, it works asynchronously — creating draft PRs,
pushing commits, and running CI. There's no easy terminal-native way to see the status of
all your agent sessions at a glance or get notified when something changes.

## Solution Overview

`agent-monitor` is a Python CLI that polls GitHub for Copilot-authored PRs assigned to you,
displays a color-coded status table using `rich`, auto-labels PRs, and sends macOS
notifications when key events occur.

---

## Data Source

### Finding Copilot PRs

**`gh search prs` does NOT work** for Copilot PRs because the author is a GitHub App
(`app/copilot-swe-agent`), and the search API cannot match app authors.

Two alternatives that work:

| Method | Works | Scope |
|--------|-------|-------|
| `gh pr list --search` | ✅ | Per-repo only |
| GraphQL `search()` | ✅ | Cross-repo |

**Decision: Use GraphQL search API** for cross-repo support in a single query.

```graphql
{
  search(
    query: "is:pr author:app/copilot-swe-agent assignee:alexus37 state:open archived:false"
    type: ISSUE
    first: 50
  ) {
    nodes {
      ... on PullRequest {
        number
        title
        url
        isDraft
        state
        updatedAt
        createdAt
        repository { nameWithOwner }
        author { login }
        labels(first: 20) { nodes { name } }
        commits(last: 1) {
          nodes {
            commit {
              statusCheckRollup {
                state
                contexts(first: 100) {
                  nodes {
                    ... on CheckRun { name conclusion status }
                    ... on StatusContext { context state description }
                  }
                }
              }
            }
          }
        }
      }
    }
  }
}
```

### Copilot Agent Session Status

**The GraphQL API does not expose Copilot agent events.** They are REST-only timeline events.

**API:** `GET /repos/{owner}/{repo}/issues/{number}/timeline`

Two event types:

```json
{ "event": "copilot_work_started",  "created_at": "2026-04-03T11:02:51Z", "actor": { "login": "alexus37" } }
{ "event": "copilot_work_finished", "created_at": "2026-04-03T11:21:38Z", "actor": { "login": "alexus37" } }
```

Both include `performed_via_github_app.slug: "copilot-swe-agent"`.

**Decision: Hybrid API approach** — GraphQL for PR search/labels/checks, REST for per-PR
timeline to detect agent start/finish.

---

## Architecture

```
┌──────────────────┐     ┌──────────────┐     ┌────────────────┐
│  GitHub API       │────▶│ State Tracker │────▶│ Notifier       │
│  (GraphQL + REST) │     │ (diff engine) │     │ (osascript)    │
└──────────────────┘     └──────┬───────┘     └────────────────┘
                                │
                  ┌─────────────┤
                  │             │
           ┌──────▼───────┐  ┌─▼────────────┐
           │ Terminal UI   │  │ Auto-Labeler  │
           │ (rich table)  │  │ (gh pr edit)  │
           └──────────────┘  └──────────────┘
```

---

## Components

### 1. GitHub Fetcher (`fetcher.py`)

- **GraphQL** via `gh api graphql`: search for Copilot PRs, returns labels + check status
  in a single query
- **REST** via `gh api`: for each PR, fetches `/repos/{owner}/{repo}/issues/{number}/timeline`
  to find `copilot_work_started` / `copilot_work_finished` events
- Returns structured list of PR objects with: agent status, CI status, labels, draft state

### 2. Auto-Labeler (`labeler.py`)

- After each fetch, checks if each PR has the **"Mark Ready When Ready"** label
- If missing, adds it via `gh pr edit <url> --add-label "Mark Ready When Ready"`
- This label triggers GitHub Actions to auto-mark draft PRs as "Ready for Review" once CI
  goes green
- Logs label additions to terminal output

### 3. State Tracker (`tracker.py`)

- Stores last-known state of each PR (keyed by `repo#number`)
- On each poll, diffs current vs previous state
- Emits change events: `copilot_started`, `copilot_finished`, `draft_to_ready`,
  `checks_passed`, `checks_failed`, `label_added`, `pr_closed`

### 4. Notifier (`notifier.py`)

- Receives change events from the state tracker
- Sends macOS notifications via `osascript -e 'display notification ...'`

### 5. Display (`display.py`)

- Uses `rich` to render a table after each poll cycle
- Columns: Repo, PR#, Title, Agent Status, CI Status, Updated, Age
- Color-coded: green=passing, red=failing, yellow=pending, blue=agent working
- Summary line: "3 active | 1 passing | 1 failing | 1 pending"

### 6. CLI Entry Point (`cli.py`)

- `agent-monitor` — start polling (default: 60s interval)
- `--interval N` — polling interval in seconds
- `--once` — single fetch + display, then exit
- `--no-notify` — disable macOS notifications
- `--query "..."` — override the default search query

---

## Notification Triggers

| Event | Signal | API Source |
|-------|--------|------------|
| Copilot started work | `copilot_work_started` timeline event | REST: `/repos/{o}/{r}/issues/{n}/timeline` |
| Copilot finished work | `copilot_work_finished` timeline event | REST: same endpoint |
| PR ready for review | `isDraft` flips `true → false` | GraphQL: `isDraft` field |
| CI passed | All checks completed, none failed | GraphQL: `statusCheckRollup.contexts` |
| CI failed (real) | Any check conclusion = `FAILURE` | GraphQL: same |
| Label auto-applied | "Mark Ready When Ready" added | Auto-labeler module |

---

## CI Conclusion Classification

This is critical — **`SKIPPED` is NOT a failure**.

| Conclusion | Classification | Action |
|------------|---------------|--------|
| `SUCCESS` | ✅ Passed | Count as passed |
| `SKIPPED` | ✅ Ignored | **Do not count as failure** |
| `NEUTRAL` | ✅ Ignored | Do not count as failure |
| `FAILURE` | ❌ Failed | Notify as real failure |
| `CANCELLED` | ⚠️ Failed | Treat as failure |
| `TIMED_OUT` | ⚠️ Failed | Treat as failure |
| `ACTION_REQUIRED` | ⚠️ Failed | Treat as failure |
| `IN_PROGRESS` | ⏳ Pending | Still running |
| `QUEUED` | ⏳ Pending | Still running |

**Overall CI status logic:**
- **Passing:** All completed checks have conclusion in {SUCCESS, SKIPPED, NEUTRAL} and no
  checks are still running
- **Failing:** Any check has conclusion in {FAILURE, CANCELLED, TIMED_OUT, ACTION_REQUIRED}
- **Pending:** Some checks still IN_PROGRESS or QUEUED, none failed yet

---

## Polling Flow (each cycle)

1. Run GraphQL search query → get list of Copilot PRs with labels + check status
2. For each PR, fetch REST timeline → get `copilot_work_started`/`copilot_work_finished`
3. **Auto-label:** for each PR missing "Mark Ready When Ready", add it via `gh pr edit`
4. Diff current state against previous state → detect changes
5. Send macOS notifications for any detected changes
6. Clear terminal, render updated `rich` table
7. Sleep for `--interval` seconds

---

## Tech Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python 3.10+ | Rich ecosystem, `rich` library for TUI |
| Terminal UI | `rich` | Tables, colors, live display |
| GitHub API | `gh` CLI (subprocess) | Leverages existing auth, zero config |
| Notifications | `osascript` | Native macOS notifications |
| Packaging | `pyproject.toml` | Modern Python packaging, `pip install -e .` |

---

## Project Structure

```
agent-monitor/
├── pyproject.toml
├── README.md
├── SPEC.md              ← this file
└── agent_monitor/
    ├── __init__.py
    ├── cli.py           # argparse entry point + main loop
    ├── fetcher.py       # GraphQL + REST API calls via gh CLI
    ├── labeler.py       # Auto-apply "Mark Ready When Ready" label
    ├── tracker.py       # State diffing & change detection
    ├── notifier.py      # macOS notification dispatch
    └── display.py       # rich table rendering
```

---

## Key Discoveries During Design

1. **`gh search prs` cannot find Copilot PRs** — the author is `app/copilot-swe-agent`
   (a GitHub App), and the search CLI doesn't support app authors. GraphQL `search()` works.

2. **Copilot agent timeline events are REST-only** — `copilot_work_started` and
   `copilot_work_finished` do not exist in the GraphQL schema. Must use
   `GET /repos/{owner}/{repo}/issues/{number}/timeline`.

3. **The "Mark Ready When Ready" label** (exact name) triggers a GitHub Actions workflow
   that auto-marks draft PRs as "Ready for Review" once CI builds go green.

4. **PR author login** is `app/copilot-swe-agent` (not `copilot` or `Copilot`).
   The `Copilot` user appears as an assignee, not the author.

---

## Open Questions / Future Ideas

- Show the linked issue for each PR?
- Add sound to notifications?
- Support filtering by repo or label?
- Persist state across restarts (SQLite)?
- Add a `--watch` mode using `rich.live` for smoother updates?
- Support Linux notifications (notify-send)?
