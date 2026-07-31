from datetime import datetime, timedelta, timezone

from auth import AuthService


def test_password_setup_and_session_authentication() -> None:
    auth = AuthService()
    auth.set_initial_password("correct horse battery staple", "correct horse battery staple")
    session = auth.login("correct horse battery staple", "127.0.0.1")
    assert session is not None
    assert auth.authenticate(session.session_id, None, False)
    assert not auth.authenticate(session.session_id, None, True)
    assert auth.authenticate(session.session_id, session.csrf_token, True)


def test_password_setup_rejects_short_password_and_mismatch() -> None:
    auth = AuthService()
    try:
        auth.set_initial_password("short", "short")
    except ValueError:
        pass
    else:
        raise AssertionError("Short password must be rejected")
    try:
        auth.set_initial_password("correct horse battery staple", "different password value")
    except ValueError:
        pass
    else:
        raise AssertionError("Mismatch must be rejected")


def test_logout_and_expired_session_revoke_access() -> None:
    auth = AuthService()
    auth.set_initial_password("correct horse battery staple", "correct horse battery staple")
    session = auth.login("correct horse battery staple", "127.0.0.1")
    assert session is not None
    auth.logout(session.session_id)
    assert not auth.authenticate(session.session_id, session.csrf_token, True)
    expired = auth.login("correct horse battery staple", "127.0.0.1")
    assert expired is not None
    expired.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    assert not auth.authenticate(expired.session_id, expired.csrf_token, True)


def test_login_rate_limit_blocks_after_five_failures() -> None:
    auth = AuthService()
    auth.set_initial_password("correct horse battery staple", "correct horse battery staple")
    for _ in range(5):
        assert auth.login("wrong password", "client") is None
    assert auth.login("correct horse battery staple", "client") is None
