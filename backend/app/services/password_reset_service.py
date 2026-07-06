import secrets

from datetime import datetime
from datetime import timedelta

from app.db.database import SessionLocal

from app.models.password_reset import PasswordReset


def create_reset_token(email):

    db = SessionLocal()

    token = secrets.token_urlsafe(32)

    reset = PasswordReset(

        email=email,

        token=token,

        expires_at=datetime.utcnow() + timedelta(minutes=30)

    )

    db.add(reset)

    db.commit()

    db.close()

    return token


def get_reset_token(token):

    db = SessionLocal()

    result = (

        db.query(PasswordReset)

        .filter(

            PasswordReset.token == token

        )

        .first()

    )

    db.close()

    return result


def delete_reset_token(token):

    db = SessionLocal()

    reset = (

        db.query(PasswordReset)

        .filter(

            PasswordReset.token == token

        )

        .first()

    )

    if reset:

        db.delete(reset)

        db.commit()

    db.close()