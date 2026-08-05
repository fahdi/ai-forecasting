"""
Deploy-time CI gate (scripts/ci_gate.py).

CI runs on every push to main, but scripts/deploy_prod.sh never consulted it:
`git pull && docker compose build` shipped whatever was on main, red or not.
These tests cover the verdict logic, which is the part that decides whether
production gets the commit.

The fetch is injected so nothing here touches the network.
"""

import pytest

from scripts.ci_gate import (
    GREEN,
    MISSING,
    PENDING,
    RED,
    UNREACHABLE,
    assert_ci_green,
    evaluate_check_runs,
)


def _run(name, status="completed", conclusion="success"):
    return {"name": name, "status": status, "conclusion": conclusion}


def test_all_jobs_passing_is_green():
    verdict, reason = evaluate_check_runs(
        [_run("Backend (pytest)"), _run("Frontend (typecheck + vitest)")]
    )
    assert verdict == GREEN
    assert "2" in reason


def test_a_failing_job_is_red_and_names_it():
    verdict, reason = evaluate_check_runs(
        [_run("Backend (pytest)", conclusion="failure"), _run("Frontend")]
    )
    assert verdict == RED
    assert "Backend (pytest)" in reason


@pytest.mark.parametrize("conclusion", ["failure", "timed_out", "cancelled", "action_required"])
def test_every_non_success_conclusion_blocks(conclusion):
    verdict, _ = evaluate_check_runs([_run("Backend", conclusion=conclusion)])
    assert verdict == RED


def test_unfinished_jobs_are_pending_not_green():
    """Deploying while CI is still running would defeat the gate."""
    verdict, reason = evaluate_check_runs(
        [_run("Backend"), _run("Frontend", status="in_progress", conclusion=None)]
    )
    assert verdict == PENDING
    assert "Frontend" in reason


def test_skipped_jobs_do_not_block():
    verdict, _ = evaluate_check_runs(
        [_run("Backend"), _run("Docs", conclusion="skipped")]
    )
    assert verdict == GREEN


def test_no_check_runs_at_all_is_missing():
    """A commit CI never saw is not the same as a commit that passed."""
    verdict, _ = evaluate_check_runs([])
    assert verdict == MISSING


def test_assert_ci_green_passes_silently_when_green(capsys):
    assert_ci_green("abc1234", fetch=lambda sha: [_run("Backend")])
    assert "abc1234" in capsys.readouterr().out


def test_assert_ci_green_aborts_on_red():
    with pytest.raises(SystemExit) as exc:
        assert_ci_green(
            "abc1234", fetch=lambda sha: [_run("Backend", conclusion="failure")]
        )
    assert exc.value.code != 0


def test_assert_ci_green_aborts_when_ci_never_ran():
    with pytest.raises(SystemExit):
        assert_ci_green("abc1234", fetch=lambda sha: [])


def test_unreachable_github_blocks_by_default():
    """Fail closed: an unverifiable commit is not a verified commit."""

    def boom(sha):
        raise OSError("network unreachable")

    verdict, reason = evaluate_check_runs(None, error="network unreachable")
    assert verdict == UNREACHABLE
    assert "network unreachable" in reason

    with pytest.raises(SystemExit):
        assert_ci_green("abc1234", fetch=boom)


def test_allow_red_overrides_every_blocking_verdict(capsys):
    """The 3am escape hatch, but it has to announce itself."""
    for fetch in (
        lambda sha: [_run("Backend", conclusion="failure")],
        lambda sha: [],
    ):
        assert_ci_green("abc1234", fetch=fetch, allow_red=True)
    out = capsys.readouterr().out
    assert out.lower().count("override") >= 2
