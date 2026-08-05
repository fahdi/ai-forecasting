#!/usr/bin/env python3
"""
Refuse to deploy a commit that CI did not pass (RUNBOOK §1).

CI (.github/workflows/ci.yml) runs the 537 pytest and 11 vitest tests on every
push to main, but that only produces a red X on GitHub — scripts/deploy_prod.sh
pulled main and rebuilt regardless. This is the gate that makes the red X mean
something: no green run for the exact SHA, no deploy.

Fails closed. "GitHub is unreachable" and "CI never ran for this commit" both
block, because neither is evidence the tests passed. For the 3am incident where
you need to ship anyway:

    ALLOW_RED_CI=1 scripts/deploy_prod.sh

which deploys and says loudly in the log that it overrode the gate.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Callable, List, Optional, Tuple

GREEN = "green"
RED = "red"
PENDING = "pending"
MISSING = "missing"
UNREACHABLE = "unreachable"

DEFAULT_REPO = "fahdi/ai-forecasting"

# GitHub reports a finished-but-not-run job as "skipped". That is a job which
# chose not to have an opinion, not a failure.
NEUTRAL_CONCLUSIONS = {"skipped", "neutral"}


def evaluate_check_runs(
    check_runs: Optional[List[dict]], error: Optional[str] = None
) -> Tuple[str, str]:
    """Decide whether a commit's check runs clear it for production.

    Returns (verdict, human-readable reason). Verdict precedence is
    unreachable > missing > red > pending > green: a definite failure outranks
    a job still in flight, and anything unproven outranks both.
    """
    if error is not None:
        return UNREACHABLE, f"could not reach GitHub: {error}"
    if not check_runs:
        return MISSING, "no CI run exists for this commit"

    failed, unfinished, passed = [], [], []
    for run in check_runs:
        name = run.get("name", "<unnamed>")
        if run.get("status") != "completed":
            unfinished.append(name)
        elif run.get("conclusion") == "success":
            passed.append(name)
        elif run.get("conclusion") in NEUTRAL_CONCLUSIONS:
            continue
        else:
            failed.append(f"{name} ({run.get('conclusion')})")

    if failed:
        return RED, "CI failed: " + ", ".join(failed)
    if unfinished:
        return PENDING, "CI still running: " + ", ".join(unfinished)
    return GREEN, f"{len(passed)} CI job(s) passed"


def fetch_check_runs(sha: str, repo: str = DEFAULT_REPO) -> List[dict]:
    """Check runs for one commit. The repo is public, so a token is optional;
    GITHUB_TOKEN is used when set to avoid the anonymous rate limit."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/commits/{sha}/check-runs",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "aif-ci-gate"},
    )
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response).get("check_runs", [])


def assert_ci_green(
    sha: str,
    fetch: Callable[[str], List[dict]] = fetch_check_runs,
    allow_red: bool = False,
) -> None:
    """Exit nonzero unless `sha` has a green CI run, unless overridden."""
    try:
        check_runs, error = fetch(sha), None
    except Exception as exc:  # network, HTTP, malformed JSON — all unproven
        check_runs, error = None, str(exc)

    verdict, reason = evaluate_check_runs(check_runs, error=error)

    if verdict == GREEN:
        print(f"ci gate: {sha} is green ({reason})")
        return
    if allow_red:
        print(f"ci gate OVERRIDE: deploying {sha} anyway — {reason}")
        return
    print(f"ci gate: refusing to deploy {sha} — {reason}", file=sys.stderr)
    print("re-run with ALLOW_RED_CI=1 to override", file=sys.stderr)
    raise SystemExit(1)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True, help="commit SHA to check")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPO", DEFAULT_REPO))
    args = parser.parse_args(argv)

    assert_ci_green(
        args.sha,
        fetch=lambda sha: fetch_check_runs(sha, repo=args.repo),
        allow_red=os.environ.get("ALLOW_RED_CI") == "1",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
