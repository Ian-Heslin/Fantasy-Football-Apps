"""Signup validation, login throttling, and the login timing channel."""
import pytest

from app import auth


@pytest.fixture(autouse=True)
def clean_throttle():
    """The throttle is process-global, so tests must not leak into each
    other."""
    auth._login_failures.clear()
    yield
    auth._login_failures.clear()


# ---------------------------------------------------------------- usernames

@pytest.mark.parametrize("username", ["ian", "ian.heslin", "ian_h", "ian-h", "a1"])
def test_reasonable_usernames_are_accepted(username):
    assert auth.validate_username(username) is None


@pytest.mark.parametrize("username", [
    "i",                       # too short
    "x" * 33,                  # too long -- used to be unbounded, and the
                               # value is rendered into every leaderboard
    "ian heslin",              # space
    "<script>alert(1)</script>",
    "ian@example.com",
])
def test_bad_usernames_are_rejected_with_a_reason(username):
    problem = auth.validate_username(username)
    assert problem and isinstance(problem, str)


# ---------------------------------------------------------------- passwords

def test_password_floor_is_enforced():
    # The old check was `if not password`, so "x" was a valid password on
    # an internet-facing site with no reset flow.
    assert auth.validate_password("x") is not None
    assert auth.validate_password("a" * (auth.MIN_PASSWORD_LENGTH - 1)) is not None
    assert auth.validate_password("a" * auth.MIN_PASSWORD_LENGTH) is None


def test_passphrases_are_fine():
    assert auth.validate_password("correct horse battery staple") is None


def test_password_longer_than_bcrypt_can_hash_is_rejected_not_truncated():
    # bcrypt ignores everything past 72 bytes; accepting a 200-character
    # password would silently only use the first 72.
    assert auth.validate_password("a" * 73) is not None
    assert auth.validate_password("a" * 72) is None


def test_password_limit_counts_bytes_not_characters():
    # 30 4-byte emoji is 120 bytes, well past bcrypt's limit, even though
    # len() says 30.
    assert auth.validate_password("🏈" * 30) is not None


def test_hash_and_verify_round_trip():
    hashed = auth.hash_password("correct horse battery staple")
    assert auth.verify_password("correct horse battery staple", hashed)
    assert not auth.verify_password("Correct horse battery staple", hashed)


def test_verify_password_survives_a_corrupt_stored_hash():
    # One malformed row must not 500 the login page for everyone.
    assert auth.verify_password("anything", "not-a-bcrypt-hash") is False


def test_missing_user_still_runs_a_real_bcrypt_check():
    # The timing channel: a hash of None used to return instantly while a
    # real username spent ~100ms in bcrypt, which distinguishes them.
    assert auth.verify_password_or_dummy("anything", None) is False


# ---------------------------------------------------------------- throttle

def test_login_is_open_until_the_failure_limit():
    for _ in range(auth.MAX_FAILED_LOGINS - 1):
        auth.record_login_failure("ian")
    assert not auth.login_is_throttled("ian")


def test_login_throttles_at_the_limit():
    for _ in range(auth.MAX_FAILED_LOGINS):
        auth.record_login_failure("ian")
    assert auth.login_is_throttled("ian")


def test_throttle_is_per_username_not_global():
    # Everyone arrives through the same tunnel address, so a global or
    # per-IP throttle would let one attacker lock out the whole site.
    for _ in range(auth.MAX_FAILED_LOGINS * 2):
        auth.record_login_failure("victim")
    assert auth.login_is_throttled("victim")
    assert not auth.login_is_throttled("someone-else")


def test_a_successful_login_clears_the_count():
    for _ in range(auth.MAX_FAILED_LOGINS - 1):
        auth.record_login_failure("ian")
    auth.clear_login_failures("ian")
    assert not auth.login_is_throttled("ian")
    for _ in range(auth.MAX_FAILED_LOGINS - 1):
        auth.record_login_failure("ian")
    assert not auth.login_is_throttled("ian")


def test_failures_age_out_of_the_window(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(auth.time, "monotonic", lambda: clock["t"])
    for _ in range(auth.MAX_FAILED_LOGINS):
        auth.record_login_failure("ian")
    assert auth.login_is_throttled("ian")

    clock["t"] += auth.LOGIN_WINDOW_SECONDS + 1
    assert not auth.login_is_throttled("ian")


# ---------------------------------------------------------------- tiers

def test_tiers_are_strictly_nested():
    assert auth.TIER_RANK["games"] < auth.TIER_RANK["fantasy"] < auth.TIER_RANK["admin"]
