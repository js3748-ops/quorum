import unittest

from backend.auth import (
    LOGIN_LOCK_SECONDS,
    LOGIN_MAX_FAILURES,
    LoginThrottle,
    authenticated_session_is_valid,
    start_authenticated_session,
)


class LoginThrottleTests(unittest.TestCase):
    def test_repeated_failures_are_temporarily_blocked(self):
        throttle = LoginThrottle()
        for offset in range(LOGIN_MAX_FAILURES):
            throttle.record_failure("person@example.com", "127.0.0.1", 100 + offset)

        self.assertGreater(
            throttle.retry_after("person@example.com", "127.0.0.1", 105), 0
        )
        self.assertEqual(
            throttle.retry_after(
                "person@example.com", "127.0.0.1", 104 + LOGIN_LOCK_SECONDS
            ),
            0,
        )

    def test_success_clears_identity_failures(self):
        throttle = LoginThrottle()
        for offset in range(LOGIN_MAX_FAILURES):
            throttle.record_failure("person@example.com", "127.0.0.1", 100 + offset)
        throttle.clear_identity("person@example.com", "127.0.0.1")

        self.assertEqual(
            throttle.retry_after("person@example.com", "127.0.0.1", 105), 0
        )


class SessionSecurityTests(unittest.TestCase):
    def test_session_has_rotating_identifier_and_activity_times(self):
        first = {}
        second = {}
        start_authenticated_session(first, 12, now=1_000)
        start_authenticated_session(second, 12, now=1_000)

        self.assertNotEqual(first["session_id"], second["session_id"])
        self.assertTrue(authenticated_session_is_valid(first, now=1_060))
        self.assertEqual(first["last_seen"], 1_060)

    def test_expired_session_is_cleared(self):
        session = {}
        start_authenticated_session(session, 12, now=1_000)

        self.assertFalse(authenticated_session_is_valid(session, now=3_000))
        self.assertEqual(session, {})


if __name__ == "__main__":
    unittest.main()
