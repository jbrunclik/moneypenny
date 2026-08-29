"""Tests for Rouvy credential storage on the users table."""

from src.db.models import Database, User


def test_rouvy_credentials_round_trip(test_database: Database, test_user: User) -> None:
    ok = test_database.update_user_rouvy_credentials(
        test_user.id, "r@example.com", "pw-secret", '[{"name":"s","value":"v"}]'
    )
    assert ok is True
    u = test_database.get_user_by_id(test_user.id)
    assert u is not None
    assert u.rouvy_email == "r@example.com"
    assert u.rouvy_password == "pw-secret"  # decrypted on hydration
    assert u.rouvy_session == '[{"name":"s","value":"v"}]'
    assert u.rouvy_connected_at is not None


def test_rouvy_disconnect_clears(test_database: Database, test_user: User) -> None:
    test_database.update_user_rouvy_credentials(test_user.id, "r@e.com", "pw", "[]")
    test_database.update_user_rouvy_credentials(test_user.id, None, None, None)
    u = test_database.get_user_by_id(test_user.id)
    assert u is not None
    assert u.rouvy_email is None
    assert u.rouvy_password is None
    assert u.rouvy_session is None
    assert u.rouvy_connected_at is None


def test_rouvy_session_refresh_only(test_database: Database, test_user: User) -> None:
    test_database.update_user_rouvy_credentials(test_user.id, "r@e.com", "pw", "[]")
    ok = test_database.update_user_rouvy_session(test_user.id, '[{"name":"new"}]')
    assert ok is True
    u = test_database.get_user_by_id(test_user.id)
    assert u is not None
    assert u.rouvy_session == '[{"name":"new"}]'
    assert u.rouvy_email == "r@e.com"  # unchanged
    assert u.rouvy_password == "pw"  # unchanged


def test_rouvy_password_encrypted_at_rest(test_database: Database, test_user: User) -> None:
    from src.utils.token_crypto import encryption_enabled

    test_database.update_user_rouvy_credentials(test_user.id, "r@e.com", "pw", "[]")
    with test_database._pool.get_connection() as conn:
        row = conn.execute(
            "SELECT rouvy_password FROM users WHERE id = ?", (test_user.id,)
        ).fetchone()
    if encryption_enabled():
        assert row["rouvy_password"] != "pw"
        assert row["rouvy_password"].startswith("enc:")
