"""
scripts/deploy_prod.sh verification behaviour.

The script bakes GIT_SHA into the api image and then asserts the running api
reports it back. Only the api image carries GIT_SHA, so `deploy_prod.sh
dashboard` printed "DEPLOY MISMATCH: built <new> but api reports <old>" and
exited nonzero on a deploy that had in fact succeeded.

A deploy tool that cries wolf gets ignored, which is worse than one that says
nothing. Exercised end to end against fake git/docker/python3 on PATH; no
network, no containers.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "deploy_prod.sh"


def _executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


@pytest.fixture
def deploy_env(tmp_path):
    """A fake checkout plus fake git/docker/python3, returning a runner."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(DEPLOY_SCRIPT, repo / "scripts" / "deploy_prod.sh")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    _executable(
        bin_dir / "git",
        '#!/usr/bin/env bash\n'
        'case "$*" in\n'
        '  "rev-parse --short HEAD") echo newsha;;\n'
        '  "rev-parse HEAD") echo newshafull;;\n'
        '  *) exit 0;;\n'
        'esac\n',
    )
    # ci_gate.py is covered by its own tests; here it just has to pass.
    _executable(bin_dir / "python3", "#!/usr/bin/env bash\nexit 0\n")

    def run(services, api_reports="newsha"):
        _executable(
            bin_dir / "docker",
            '#!/usr/bin/env bash\n'
            'for arg in "$@"; do\n'
            '  case "$arg" in\n'
            '    ps) echo "Up (healthy)"; exit 0;;\n'
            f'    python) echo "{api_reports}"; exit 0;;\n'
            '  esac\n'
            'done\n'
            'exit 0\n',
        )
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}")
        return subprocess.run(
            ["bash", "scripts/deploy_prod.sh", *services],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    return run


def test_deploying_api_still_verifies_the_live_sha(deploy_env):
    result = deploy_env(["api", "dashboard"])
    assert result.returncode == 0, result.stderr
    assert "deploy ok" in result.stdout


def test_sha_mismatch_still_fails_loudly(deploy_env):
    """The guard that catches a stale container must keep working."""
    result = deploy_env(["api"], api_reports="oldsha")
    assert result.returncode != 0
    assert "DEPLOY MISMATCH" in result.stdout + result.stderr


def test_dashboard_only_deploy_does_not_report_a_false_mismatch(deploy_env):
    """The regression: api is untouched, so its SHA proves nothing."""
    result = deploy_env(["dashboard"], api_reports="oldsha")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "DEPLOY MISMATCH" not in result.stdout + result.stderr


def test_skipped_verification_says_so_rather_than_claiming_success(deploy_env):
    """Silence would read as a verified deploy; it was not verified."""
    result = deploy_env(["dashboard"], api_reports="oldsha")
    assert "skip" in result.stdout.lower()
    assert "api" in result.stdout.lower()
