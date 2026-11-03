"""Emergency local password reset (interactive, avoids shell history)."""
import argparse
import getpass
from sqlalchemy import delete, select
from . import models
from .auth import ph
from .db import SessionLocal


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("reset-password", choices=["reset-password"])
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    password = getpass.getpass("New password (14+ characters): ")
    if len(password) < 14:
        raise SystemExit("Password too short")
    verify = getpass.getpass("Repeat new password: ")
    if password != verify:
        raise SystemExit("Passwords do not match")
    with SessionLocal() as db:
        user = db.scalar(select(models.User).where(models.User.email == args.email.lower()))
        if not user:
            raise SystemExit("User not found")
        user.password_hash = ph.hash(password)
        user.failed_attempts = 0
        user.locked_until = 0
        db.execute(delete(models.LoginSession).where(models.LoginSession.user_id == user.id))
        db.commit()
    print("Password changed; existing sessions revoked.")


if __name__ == "__main__":
    main()
