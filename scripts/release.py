#!/usr/bin/env python3
"""
Cut a release: bump the version, tag it, push it, publish GitHub release notes.

The repo carried four hardcoded version strings that already disagreed
(1.0.0 in the API, 0.1.0 in the dashboard) and had no tags at all, so there
was no way to say which code a given deploy corresponds to beyond a git SHA.
The VERSION file at the repo root is now the single source of truth; this
script is the only thing that edits it.

Preflight refuses to tag anything that is not actually releasable: a dirty
tree, a side branch, a commit whose CI is not green, or a tag that already
exists. It reports every problem at once rather than one per run.

    scripts/release.py minor -m "Scheduled retraining"
    scripts/release.py patch --dry-run

Deliberately does NOT deploy. scripts/deploy_prod.sh stays the deploy path,
and it has its own CI gate.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import FrozenSet, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

VERSION_FILE_REL = "VERSION"
PACKAGE_JSON_REL = "frontend/package.json"

_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
BUMP_PARTS = ("major", "minor", "patch")


def parse_version(text: str) -> Tuple[int, int, int]:
    match = _SEMVER.match((text or "").strip())
    if not match:
        raise ValueError(f"not a plain semver version: {text!r}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def bump_version(current: str, part: str) -> str:
    if part not in BUMP_PARTS:
        raise ValueError(f"bump part must be one of {BUMP_PARTS}, got {part!r}")
    major, minor, patch = parse_version(current)
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def tag_for(version: str) -> str:
    return f"v{version}"


def read_version(root: Path) -> str:
    return (Path(root) / VERSION_FILE_REL).read_text().strip()


def write_version(root: Path, version: str) -> List[Path]:
    """Update every file carrying the version. Returns what changed."""
    parse_version(version)
    root = Path(root)
    changed = []

    version_file = root / VERSION_FILE_REL
    version_file.write_text(f"{version}\n")
    changed.append(version_file)

    package_path = root / PACKAGE_JSON_REL
    package = json.loads(package_path.read_text())
    package["version"] = version
    # Preserve key order and npm's two-space formatting so the diff is one line.
    package_path.write_text(json.dumps(package, indent=2) + "\n")
    changed.append(package_path)

    return changed


def preflight(
    branch: str,
    dirty: bool,
    ci_green: bool,
    tag: str,
    existing_tags: FrozenSet[str],
) -> List[str]:
    """Every reason this commit must not be tagged. Empty means go."""
    reasons = []
    if dirty:
        reasons.append("working tree has uncommitted changes")
    if branch != "main":
        reasons.append(f"on branch {branch!r}, releases are cut from main")
    if not ci_green:
        reasons.append("CI is not green for HEAD; a tag would point at unverified code")
    if tag in existing_tags:
        reasons.append(f"tag {tag} already exists")
    return reasons


# --- git / gh plumbing -------------------------------------------------------


def _git(*args: str, root: Optional[Path] = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=str(root) if root else None,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _ci_is_green(sha: str) -> bool:
    from scripts.ci_gate import GREEN, evaluate_check_runs, fetch_check_runs

    try:
        runs, error = fetch_check_runs(sha), None
    except Exception as exc:
        runs, error = None, str(exc)
    verdict, _ = evaluate_check_runs(runs, error=error)
    return verdict == GREEN


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part", choices=BUMP_PARTS)
    parser.add_argument("-m", "--message", default="", help="release headline")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    current = read_version(root)
    new_version = bump_version(current, args.part)
    tag = tag_for(new_version)

    reasons = preflight(
        branch=_git("rev-parse", "--abbrev-ref", "HEAD", root=root),
        dirty=bool(_git("status", "--porcelain", root=root)),
        ci_green=_ci_is_green(_git("rev-parse", "HEAD", root=root)),
        tag=tag,
        existing_tags=frozenset(_git("tag", "--list", root=root).split()),
    )
    if reasons:
        print(f"refusing to release {tag}:", file=sys.stderr)
        for reason in reasons:
            print(f"  - {reason}", file=sys.stderr)
        return 1

    print(f"{current} -> {new_version} ({tag})")
    if args.dry_run:
        print("dry run; nothing written")
        return 0

    for path in write_version(root, new_version):
        print(f"  updated {path.relative_to(root)}")

    headline = args.message or f"Release {tag}"
    _git("add", VERSION_FILE_REL, PACKAGE_JSON_REL, root=root)
    _git("commit", "-m", f"Release {tag}: {headline}" if args.message else f"Release {tag}", root=root)
    _git("tag", "-a", tag, "-m", headline, root=root)
    _git("push", "origin", "main", root=root)
    _git("push", "origin", tag, root=root)

    subprocess.run(
        ["gh", "release", "create", tag, "--title", f"{tag} {headline}".strip(),
         "--generate-notes"],
        cwd=str(root),
        check=True,
    )
    print(f"released {tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
