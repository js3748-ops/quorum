import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import AuthChallenge
from backend.services.otp import (
    OTP_MAX_ATTEMPTS,
    OtpRateLimitError,
    consume_otp_challenge,
    create_otp_challenge,
)


class OtpChallengeTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.sent_codes = []
        self.sender = patch(
            "backend.services.otp.send_otp_email",
            side_effect=lambda email, otp, purpose: self.sent_codes.append(otp),
        )
        self.sender.start()

    def tearDown(self):
        self.sender.stop()
        self.db.close()

    def create_challenge(self):
        return create_otp_challenge(
            self.db,
            purpose="login",
            email="person@example.com",
            user_id=7,
        )

    def test_code_is_hashed_single_use_and_not_returned(self):
        challenge = self.create_challenge()
        otp = self.sent_codes[-1]

        self.assertNotEqual(challenge.otp_digest, otp)
        self.assertNotIn(otp, challenge.otp_digest)
        self.assertIsNotNone(
            consume_otp_challenge(
                self.db,
                challenge_id=challenge.id,
                otp=otp,
                purpose="login",
            )
        )
        self.db.commit()
        self.assertIsNone(
            consume_otp_challenge(
                self.db,
                challenge_id=challenge.id,
                otp=otp,
                purpose="login",
            )
        )

    def test_attempt_limit_blocks_the_correct_code(self):
        challenge = self.create_challenge()
        otp = self.sent_codes[-1]
        for _ in range(OTP_MAX_ATTEMPTS):
            self.assertIsNone(
                consume_otp_challenge(
                    self.db,
                    challenge_id=challenge.id,
                    otp="000000" if otp != "000000" else "999999",
                    purpose="login",
                )
            )

        self.assertIsNone(
            consume_otp_challenge(
                self.db,
                challenge_id=challenge.id,
                otp=otp,
                purpose="login",
            )
        )

    def test_expired_code_is_rejected(self):
        challenge = self.create_challenge()
        otp = self.sent_codes[-1]
        stored = self.db.get(AuthChallenge, challenge.id)
        stored.expires_at = datetime.utcnow() - timedelta(seconds=1)
        self.db.commit()

        self.assertIsNone(
            consume_otp_challenge(
                self.db,
                challenge_id=challenge.id,
                otp=otp,
                purpose="login",
            )
        )

    def test_immediate_resend_is_throttled(self):
        self.create_challenge()

        with self.assertRaises(OtpRateLimitError):
            self.create_challenge()


if __name__ == "__main__":
    unittest.main()
