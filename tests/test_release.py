"""
Release mechanics (scripts/release.py).

The repo had no tags and no GitHub releases, and four hardcoded version
strings that already disagreed: app/core/config.py and app/main.py and
app/api/v1/endpoints/health.py said 1.0.0 while frontend/package.json said
0.1.0. Shipping "a release every time" needs one source of truth and a
mechanism that refuses to tag something that is not actually releasable.

The preflight is the important part. Tagging a dirty tree, a side branch, or a
commit whose CI is red produces a tag that does not correspond to anything
that was ever verified.
"""

import json

from pathlib import Path

import pytest

from scripts.release import (
    PACKAGE_JSON_REL,
    VERSION_FILE_REL,
    bump_version,
    parse_version,
    preflight,
    read_version,
    write_version,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestVersionArithmetic:
    @pytest.mark.parametrize(
        "current,part,expected",
        [
            ("1.0.0", "patch", "1.0.1"),
            ("1.0.9", "patch", "1.0.10"),
            ("1.2.3", "minor", "1.3.0"),
            ("1.2.3", "major", "2.0.0"),
            ("0.9.9", "minor", "0.10.0"),
        ],
    )
    def test_bumps(self, current, part, expected):
        assert bump_version(current, part) == expected

    def test_minor_and_major_reset_lower_parts(self):
        assert bump_version("1.4.7", "minor") == "1.5.0"
        assert bump_version("1.4.7", "major") == "2.0.0"

    @pytest.mark.parametrize("bad", ["1.0", "v1.0.0", "1.0.0-rc1", "", "a.b.c"])
    def test_rejects_malformed_versions(self, bad):
        with pytest.raises(ValueError):
            parse_version(bad)

    def test_rejects_unknown_bump_part(self):
        with pytest.raises(ValueError):
            bump_version("1.0.0", "epoch")


class TestVersionSourceOfTruth:
    def test_version_file_exists_and_parses(self):
        assert parse_version(read_version(REPO_ROOT))

    def test_every_version_source_agrees(self):
        """Drift here is how the API and the dashboard ended up disagreeing."""
        canonical = read_version(REPO_ROOT)

        from app.core.config import settings

        assert settings.VERSION == canonical, "app/core/config.py is out of step"

        package = json.loads((REPO_ROOT / PACKAGE_JSON_REL).read_text())
        assert package["version"] == canonical, "frontend/package.json is out of step"

    def test_no_stray_hardcoded_versions_remain(self):
        """main.py and health.py used to carry their own literal copies."""
        for rel in ("app/main.py", "app/api/v1/endpoints/health.py"):
            source = (REPO_ROOT / rel).read_text()
            assert '"1.0.0"' not in source, f"{rel} still hardcodes a version"

    def test_write_version_updates_both_files(self, tmp_path):
        (tmp_path / VERSION_FILE_REL).write_text("1.0.0\n")
        frontend = tmp_path / "frontend"
        frontend.mkdir()
        (tmp_path / PACKAGE_JSON_REL).write_text(
            json.dumps({"name": "frontend", "version": "1.0.0", "scripts": {}}, indent=2)
            + "\n"
        )

        changed = write_version(tmp_path, "1.1.0")

        assert read_version(tmp_path) == "1.1.0"
        assert json.loads((tmp_path / PACKAGE_JSON_REL).read_text())["version"] == "1.1.0"
        assert len(changed) == 2

    def test_write_version_preserves_other_package_json_keys(self, tmp_path):
        (tmp_path / VERSION_FILE_REL).write_text("1.0.0\n")
        (tmp_path / "frontend").mkdir()
        original = {"name": "frontend", "version": "1.0.0", "scripts": {"test": "vitest run"}}
        (tmp_path / PACKAGE_JSON_REL).write_text(json.dumps(original, indent=2) + "\n")

        write_version(tmp_path, "1.1.0")

        package = json.loads((tmp_path / PACKAGE_JSON_REL).read_text())
        assert package["scripts"] == {"test": "vitest run"}
        assert package["name"] == "frontend"


class TestPreflight:
    """Every reason a commit is not releasable, and it reports all of them."""

    def _ok(self, **overrides):
        base = dict(
            branch="main",
            dirty=False,
            ci_green=True,
            tag="v1.1.0",
            existing_tags=frozenset({"v1.0.0"}),
        )
        base.update(overrides)
        return base

    def test_clean_state_passes(self):
        assert preflight(**self._ok()) == []

    def test_dirty_tree_blocks(self):
        reasons = preflight(**self._ok(dirty=True))
        assert any("uncommitted" in r for r in reasons)

    def test_side_branch_blocks(self):
        reasons = preflight(**self._ok(branch="feature/x"))
        assert any("main" in r for r in reasons)

    def test_red_ci_blocks(self):
        """A tag on a red commit points at something never verified."""
        reasons = preflight(**self._ok(ci_green=False))
        assert any("CI" in r for r in reasons)

    def test_existing_tag_blocks(self):
        reasons = preflight(**self._ok(tag="v1.0.0"))
        assert any("already exists" in r for r in reasons)

    def test_reports_every_problem_not_just_the_first(self):
        """Fixing one blocker at a time across three CI round trips is waste."""
        reasons = preflight(
            **self._ok(branch="wip", dirty=True, ci_green=False, tag="v1.0.0")
        )
        assert len(reasons) == 4


class TestTagFormat:
    def test_tag_is_v_prefixed(self):
        from scripts.release import tag_for

        assert tag_for("1.2.3") == "v1.2.3"


class TestRepoState:
    def test_release_script_is_executable(self):
        assert (REPO_ROOT / "scripts" / "release.py").stat().st_mode & 0o111

    # Deliberately no "a v* tag exists" test: actions/checkout does a shallow
    # fetch without tags, so `git tag --list` is empty in CI no matter what the
    # remote holds. It would fail forever rather than guard anything.
