"""GitHub API fetcher — GraphQL for PR search, REST for Copilot timeline events."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone


GRAPHQL_QUERY = """
{
  search(
    query: "%QUERY%"
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
        reviewDecision
        mergeStateStatus
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
"""

PASS_CONCLUSIONS = {"SUCCESS", "SKIPPED", "NEUTRAL"}
FAIL_CONCLUSIONS = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
PENDING_STATUSES = {"IN_PROGRESS", "QUEUED"}


@dataclass
class CheckInfo:
    name: str
    status: str  # COMPLETED, IN_PROGRESS, QUEUED
    conclusion: str | None  # SUCCESS, FAILURE, SKIPPED, etc.
    is_required: bool = False


@dataclass
class PRStatus:
    repo: str
    number: int
    title: str
    url: str
    is_draft: bool
    state: str
    updated_at: str
    created_at: str
    author: str
    labels: list[str] = field(default_factory=list)
    checks: list[CheckInfo] = field(default_factory=list)
    ci_rollup: str = "UNKNOWN"  # PENDING, SUCCESS, FAILURE, UNKNOWN
    review_decision: str = "UNKNOWN"  # APPROVED, CHANGES_REQUESTED, REVIEW_REQUIRED, UNKNOWN
    merge_state_status: str = "UNKNOWN"  # BEHIND, BLOCKED, CLEAN, DIRTY, DRAFT, HAS_HOOKS, UNKNOWN, UNSTABLE
    agent_status: str = "unknown"  # working, finished, unknown
    agent_started_at: str | None = None
    agent_finished_at: str | None = None

    @property
    def key(self) -> str:
        return f"{self.repo}#{self.number}"

    @property
    def pr_status(self) -> str:
        """Compute PR status: draft, open, in_merge_queue, ready_to_merge."""
        if self.is_draft:
            return "draft"
        if self.merge_state_status in ("CLEAN", "HAS_HOOKS") and self.state == "OPEN":
            return "ready_to_merge"
        if self.merge_state_status == "UNSTABLE" and self.state == "OPEN":
            # In merge queue or queued
            return "in_merge_queue"
        # Check if CI passed + approved + not draft → ready to merge
        if (not self.is_draft and self.state == "OPEN"
                and self.ci_status == "passed"
                and self.review_decision == "APPROVED"):
            return "ready_to_merge"
        return "open"

    @property
    def ci_status(self) -> str:
        """Compute CI status from required checks only (falls back to all checks)."""
        if not self.checks:
            return "unknown"

        required = [c for c in self.checks if c.is_required]
        relevant = required if required else self.checks

        has_failure = any(c.conclusion in FAIL_CONCLUSIONS for c in relevant)
        if has_failure:
            return "failed"

        has_pending = any(
            c.status in PENDING_STATUSES or (c.status == "IN_PROGRESS")
            for c in relevant
            if c.conclusion is None
        )
        if has_pending:
            return "pending"

        has_pass = any(c.conclusion in PASS_CONCLUSIONS for c in relevant)
        if has_pass:
            return "passed"

        return "unknown"

    @property
    def age(self) -> str:
        try:
            created = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - created
            hours = int(delta.total_seconds() // 3600)
            if hours < 1:
                return f"{int(delta.total_seconds() // 60)}m"
            if hours < 24:
                return f"{hours}h"
            return f"{hours // 24}d"
        except Exception:
            return "?"


def _run_gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def fetch_prs(query: str) -> list[PRStatus]:
    """Fetch Copilot PRs via GraphQL and enrich with REST timeline data."""
    gql = GRAPHQL_QUERY.replace("%QUERY%", query.replace('"', '\\"'))
    raw = _run_gh("api", "graphql", "-f", f"query={gql}")
    data = json.loads(raw)

    prs: list[PRStatus] = []
    for node in data.get("data", {}).get("search", {}).get("nodes", []):
        if not node or not node.get("number"):
            continue

        labels = [l["name"] for l in node.get("labels", {}).get("nodes", [])]

        checks: list[CheckInfo] = []
        rollup_state = "UNKNOWN"
        commits = node.get("commits", {}).get("nodes", [])
        if commits:
            rollup = commits[0].get("commit", {}).get("statusCheckRollup")
            if rollup:
                rollup_state = rollup.get("state", "UNKNOWN")
                for ctx in rollup.get("contexts", {}).get("nodes", []):
                    if "name" in ctx:
                        checks.append(CheckInfo(
                            name=ctx["name"],
                            status=ctx.get("status", ""),
                            conclusion=ctx.get("conclusion"),
                        ))
                    elif "context" in ctx:
                        checks.append(CheckInfo(
                            name=ctx["context"],
                            status="COMPLETED" if ctx.get("state") == "SUCCESS" else ctx.get("state", ""),
                            conclusion=ctx.get("state"),
                        ))

        pr = PRStatus(
            repo=node["repository"]["nameWithOwner"],
            number=node["number"],
            title=node["title"],
            url=node["url"],
            is_draft=node.get("isDraft", False),
            state=node.get("state", ""),
            updated_at=node.get("updatedAt", ""),
            created_at=node.get("createdAt", ""),
            author=node.get("author", {}).get("login", ""),
            labels=labels,
            checks=checks,
            ci_rollup=rollup_state,
            review_decision=node.get("reviewDecision") or "UNKNOWN",
            merge_state_status=node.get("mergeStateStatus") or "UNKNOWN",
        )
        prs.append(pr)

    # Enrich with timeline data and required check status
    for pr in prs:
        _enrich_agent_status(pr)
        _enrich_required_checks(pr)

    return prs


def _enrich_agent_status(pr: PRStatus) -> None:
    """Fetch REST timeline to find copilot_work_started/finished events."""
    try:
        raw = _run_gh(
            "api", f"repos/{pr.repo}/issues/{pr.number}/timeline",
            "--paginate", "--jq",
            '[.[] | select(.event == "copilot_work_started" or .event == "copilot_work_finished") | {event, created_at}]',
        )
        events = json.loads(raw) if raw.strip() else []
    except Exception:
        return

    started_at = None
    finished_at = None
    for evt in events:
        if evt["event"] == "copilot_work_started":
            started_at = evt["created_at"]
        elif evt["event"] == "copilot_work_finished":
            finished_at = evt["created_at"]

    pr.agent_started_at = started_at
    pr.agent_finished_at = finished_at

    if finished_at and (not started_at or finished_at >= started_at):
        pr.agent_status = "finished"
    elif started_at and not finished_at:
        pr.agent_status = "working"
    elif started_at and finished_at and started_at > finished_at:
        # Re-triggered after a previous finish
        pr.agent_status = "working"
    else:
        pr.agent_status = "unknown"


REQUIRED_CHECKS_QUERY = """
{
  resource(url: "%URL%") {
    ... on PullRequest {
      commits(last: 1) {
        nodes {
          commit {
            statusCheckRollup {
              contexts(first: 100) {
                nodes {
                  ... on CheckRun {
                    name
                    isRequired(pullRequestNumber: %NUMBER%)
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
"""


def _enrich_required_checks(pr: PRStatus) -> None:
    """Mark checks as required/optional using the isRequired GraphQL field."""
    try:
        gql = REQUIRED_CHECKS_QUERY.replace("%URL%", pr.url).replace("%NUMBER%", str(pr.number))
        raw = _run_gh("api", "graphql", "-f", f"query={gql}")
        data = json.loads(raw)
    except Exception:
        return

    required_names: set[str] = set()
    commits = data.get("data", {}).get("resource", {}).get("commits", {}).get("nodes", [])
    if commits:
        rollup = commits[0].get("commit", {}).get("statusCheckRollup")
        if rollup:
            for ctx in rollup.get("contexts", {}).get("nodes", []):
                if ctx.get("isRequired"):
                    required_names.add(ctx["name"])

    for check in pr.checks:
        check.is_required = check.name in required_names
