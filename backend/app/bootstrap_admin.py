"""One-time bootstrap: ensure a default admin account exists so a fresh
install has someone who can log in and use the Admin tab immediately,
without the chicken-and-egg problem of needing an account to create your
first account. Idempotent — does nothing if that email is already
registered, so re-running install.sh never resets an existing admin's
password out from under them.

The login/registration schemas require a real-looking email address (see
app/schemas.py's EmailStr fields) — "admin@localhost" and similar
local/reserved domains are rejected by the same validator a login attempt
would hit, so this can't literally be the bare username "admin". Using
"admin" as the address's local part is the closest equivalent that still
actually works.

Run via: python3 -m app.bootstrap_admin [email]
Prints exactly one line to stdout so install.sh can parse the result
without scraping log output: "created:<email>:<password>", "exists:<email>",
or "error:<message>".
"""

from __future__ import annotations

import secrets
import sys

from app.auth import hash_password
from app.db import SessionLocal, init_db
from app.models import User

DEFAULT_EMAIL = "admin@example.com"
PASSWORD_LENGTH = 10
# Excludes visually-ambiguous characters (0/O, 1/l/I) since this password
# is meant to be read off a terminal and typed in, not copy-pasted.
PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def main() -> None:
    email = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL).lower()
    try:
        init_db()
        db = SessionLocal()
        try:
            if db.query(User).filter(User.email == email).first() is not None:
                print(f"exists:{email}")
                return
            password = generate_password()
            db.add(User(email=email, hashed_password=hash_password(password)))
            db.commit()
            print(f"created:{email}:{password}")
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - surfaced to install.sh, not swallowed
        print(f"error:{exc}")


if __name__ == "__main__":
    main()
