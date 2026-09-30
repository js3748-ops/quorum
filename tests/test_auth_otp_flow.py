import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.auth import hash_password
from backend.database import Base
from backend.models import User
from backend.routes.auth import login, signup, verify_login, verify_signup
from backend.schemas import LoginRequest, OtpVerifyRequest, SignupRequest


class AuthOtpFlowTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        password_hash, password_salt = hash_password("strong-password")
        self.db.add(
            User(
                name="Login Person",
                email="login@example.com",
                password_hash=password_hash,
                password_salt=password_salt,
                role="student",
                department="CSE",
                id_number="OTP-LOGIN-1",
                year_of_study=2,
            )
        )
        self.db.commit()
        self.sent_codes = {}
        self.sender = patch(
            "backend.services.otp.send_otp_email",
            side_effect=lambda email, otp, purpose: self.sent_codes.__setitem__(
                (email, purpose), otp
            ),
        )
        self.sender.start()

    def tearDown(self):
        self.sender.stop()
        self.db.close()

    @staticmethod
    def request():
        return SimpleNamespace(session={}, client=SimpleNamespace(host="otp-test"))

    def test_login_requires_and_consumes_otp_before_session(self):
        request = self.request()
        started = login(
            LoginRequest(email="login@example.com", password="strong-password"),
            request,
            self.db,
        )
        self.assertNotIn("user_id", request.session)
        otp = self.sent_codes[("login@example.com", "login")]

        verified = verify_login(
            OtpVerifyRequest(challenge_id=started["challenge_id"], otp=otp),
            request,
            self.db,
        )
        self.assertEqual(verified["user"].email, "login@example.com")
        self.assertEqual(request.session["user_id"], verified["user"].id)

    def test_signup_creates_user_only_after_otp(self):
        request = self.request()
        started = signup(
            SignupRequest(
                name="New Person",
                email="new@example.com",
                password="strong-password",
                role="student",
                department="ECE",
                id_number="OTP-SIGNUP-1",
                year_of_study=1,
            ),
            self.db,
        )
        self.assertIsNone(
            self.db.scalar(select(User).where(User.email == "new@example.com"))
        )

        verified = verify_signup(
            OtpVerifyRequest(
                challenge_id=started["challenge_id"],
                otp=self.sent_codes[("new@example.com", "signup")],
            ),
            request,
            self.db,
        )
        self.assertEqual(verified["user"].email, "new@example.com")
        self.assertEqual(request.session["user_id"], verified["user"].id)


if __name__ == "__main__":
    unittest.main()
