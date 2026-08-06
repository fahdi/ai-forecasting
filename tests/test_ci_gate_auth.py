"""
Authentication and rate limits for the CI gate (issue #52).

Hit live while cutting v1.3.0. scripts/release.py refused with "CI is not green
for HEAD" on a commit whose CI was in fact green. The real cause was
HTTP 403: rate limit exceeded - fetch_check_runs only sends an Authorization
header when GITHUB_TOKEN is set, and the anonymous GitHub API allows 60
requests per hour per IP, which a busy session exhausts.

Failing closed on an unverifiable answer is correct and must not change. The
defect is that a rate limit was indistinguishable from an outage in the
message, and the workaround (GITHUB_TOKEN=$(gh auth token)) was undiscoverable.
"""

import urllib.error

import pytest

from scripts.ci_gate import (
    GREEN,
    RATE_LIMITED,
    UNREACHABLE,
    classify_fetch_error,
    resolve_token,
)


def _http_error(code, headers=None):
    return urllib.error.HTTPError(
        url="https://api.github.com/x",
        code=code,
        msg="rate limit exceeded" if code == 403 else "boom",
        hdrs=headers or {},
        fp=None,
    )


class TestTokenResolution:
    def test_env_token_wins(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "from-env")
        assert resolve_token(gh_token=lambda: "from-gh") == "from-env"

    def test_falls_back_to_the_gh_cli(self, monkeypatch):
        """The workaround that was undiscoverable becomes the default."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert resolve_token(gh_token=lambda: "from-gh") == "from-gh"

    def test_returns_none_when_neither_is_available(self, monkeypatch):
        """The VPS has no gh installed; anonymous must still work."""
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        assert resolve_token(gh_token=lambda: None) is None

    def test_a_failing_gh_cli_is_not_fatal(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)

        def boom():
            raise OSError("gh not found")

        assert resolve_token(gh_token=boom) is None

    def test_blank_values_are_treated_as_absent(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "   ")
        assert resolve_token(gh_token=lambda: "") is None


class TestErrorClassification:
    def test_rate_limit_gets_its_own_status_and_names_itself(self):
        status, message = classify_fetch_error(_http_error(403))
        assert status == RATE_LIMITED
        assert "rate limit" in message.lower()

    def test_rate_limit_message_says_how_to_fix_it(self):
        """The whole defect was that the workaround was undiscoverable."""
        _, message = classify_fetch_error(_http_error(403))
        assert "GITHUB_TOKEN" in message

    def test_rate_limit_reports_the_reset_time_when_github_supplies_it(self):
        error = _http_error(403, headers={"X-RateLimit-Reset": "1785952800"})
        _, message = classify_fetch_error(error)
        assert "2026-08-05" in message or "reset" in message.lower()

    def test_a_missing_reset_header_does_not_raise(self):
        status, message = classify_fetch_error(_http_error(403))
        assert status == RATE_LIMITED
        assert message

    def test_other_http_errors_stay_unreachable(self):
        status, _ = classify_fetch_error(_http_error(500))
        assert status == UNREACHABLE

    def test_a_422_for_an_unknown_sha_stays_unreachable(self):
        """The existing behaviour for a SHA GitHub does not know."""
        status, _ = classify_fetch_error(_http_error(422))
        assert status == UNREACHABLE

    def test_network_errors_stay_unreachable(self):
        status, message = classify_fetch_error(OSError("network is unreachable"))
        assert status == UNREACHABLE
        assert "network is unreachable" in message


class TestStillFailsClosed:
    def test_rate_limited_is_not_green(self):
        """The point of the gate: an answer we could not obtain is not a pass."""
        assert RATE_LIMITED != GREEN

    def test_assert_ci_green_still_blocks_on_a_rate_limit(self):
        from scripts.ci_gate import assert_ci_green

        def rate_limited(sha):
            raise _http_error(403)

        with pytest.raises(SystemExit):
            assert_ci_green("abc1234", fetch=rate_limited)

    def test_the_rate_limit_reason_reaches_the_operator(self, capsys):
        from scripts.ci_gate import assert_ci_green

        def rate_limited(sha):
            raise _http_error(403)

        with pytest.raises(SystemExit):
            assert_ci_green("abc1234", fetch=rate_limited)

        combined = capsys.readouterr()
        assert "rate limit" in (combined.out + combined.err).lower()
