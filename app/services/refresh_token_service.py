from datetime import datetime
from datetime import timedelta

from app.db.database import SessionLocal
from app.models.refresh_token import RefreshToken

REFRESH_TOKEN_EXPIRE_DAYS = 7


def save_refresh_token(
    user_id: str,
    token: str
):

    db = SessionLocal()

    existing = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id
        )
        .first()
    )

    if existing:

        existing.token = token

        existing.expires_at = (
            datetime.utcnow()
            + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        )

    else:

        refresh = RefreshToken(

            user_id=user_id,

            token=token,

            expires_at=(
                datetime.utcnow()
                + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
            )

        )

        db.add(refresh)

    db.commit()
    db.close()


def get_refresh_token(token: str):

    db = SessionLocal()

    refresh = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token == token
        )
        .first()
    )

    db.close()

    return refresh


def revoke_refresh_token(token: str):

    db = SessionLocal()

    refresh = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.token == token
        )
        .first()
    )

    if refresh:

        db.delete(refresh)

        db.commit()

    db.close()


def revoke_all_user_tokens(user_id: str):

    db = SessionLocal()

    tokens = (
        db.query(RefreshToken)
        .filter(
            RefreshToken.user_id == user_id
        )
        .all()
    )

    for token in tokens:

        db.delete(token)

    db.commit()

    db.close()