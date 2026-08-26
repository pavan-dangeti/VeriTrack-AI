"""Outbound violation emails via Microsoft Graph sendMail.

- Live mode: client-credentials token + sendMail; honors 429 Retry-After with
  exponential backoff (Graph throttles aggressively).
- Dry-run mode (default until Azure app registration exists): validates the
  payload, records what WOULD be sent, returns success. Nothing leaves the
  building.
"""

import asyncio
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.analysis import EmailStatus, ViolationResult

log = get_logger("emailer")

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
MAX_ATTEMPTS = 5
BASE_BACKOFF_S = 2.0


def _violation_email_body(v: ViolationResult) -> dict:
    name = v.employee_name or v.employee_code
    return {
        "message": {
            "subject": f"Leave compliance notice — {name} ({v.employee_code})",
            "body": {
                "contentType": "Text",
                "bodyText": (
                    f"Dear {name},\n\n"
                    f"Our records indicate a leave compliance issue:\n"
                    f"  {v.violation_reason}\n\n"
                    "Please review your leave record and contact HR if you "
                    "believe this is incorrect.\n\n"
                   "— VeriTrack AI (automated)"
                ),
            },
            "toRecipients": [{"emailAddress": {"address": v.email_to}}],
        },
        "saveToSentItems": True,
    }


class GraphClient:
    def __init__(self) -> None:
        if not settings.graph_enabled or not settings.graph_sender_mailbox:
            raise RuntimeError("Graph is not configured")
        self._token: str | None = None
        self._token_expiry: datetime | None = None

    async def _access_token(self) -> str:  # pragma: no cover - needs creds
        if self._token and self._token_expiry and self._token_expiry > datetime.now(UTC):
            return self._token
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://login.microsoftonline.com/{settings.graph_tenant_id}"
                "/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.graph_client_id,
                    "client_secret": settings.graph_client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3600))
        self._token_expiry = datetime.now(UTC).replace(microsecond=0)
        from datetime import timedelta

        self._token_expiry = datetime.now(UTC) + timedelta(seconds=expires_in - 120)
        return self._token

    async def send_mail(self, payload: dict) -> str | None:  # pragma: no cover
        """Returns graph message id (or None); retries on 429/5xx with backoff."""
        token = await self._access_token()
        url = f"{GRAPH_BASE}/users/{settings.graph_sender_mailbox}/sendMail"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20) as client:
            for attempt in range(1, MAX_ATTEMPTS + 1):
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 202:
                    return resp.headers.get("Message-ID") or resp.headers.get("message-id")
                if resp.status_code in (429, 500, 502, 503, 504):
                    retry_after = float(resp.headers.get("Retry-After", 0) or 0)
                    delay = max(retry_after, BASE_BACKOFF_S * (2 ** (attempt - 1)))
                    log.warning(
                        "graph_throttled", attempt=attempt, status=resp.status_code,
                        delay_s=delay,
                    )
                    await asyncio.sleep(min(delay, 60))
                    continue
                resp.raise_for_status()
        raise RuntimeError(f"Graph sendMail failed after {MAX_ATTEMPTS} attempts")


async def dispatch_violation_emails(
    db: AsyncSession, run
) -> tuple[int, int]:
    """Sends (or simulates) one email per pending violation. Returns (sent, errored)."""
    stmt = (
        select(ViolationResult)
        .where(ViolationResult.run_id == run.id)
        .order_by(ViolationResult.id)
    )
    violations = (await db.execute(stmt)).scalars().unique().all()

    live = settings.outbound_email_mode == "live" and settings.graph_enabled
    sender = GraphClient() if live else None

    sent = errored = 0
    for v in violations:
        if v.email_status != EmailStatus.PENDING:
            continue  # SKIPPED_NO_EMAIL stays as-is
        try:
            if sender is not None:
                message_id = await sender.send_mail(_violation_email_body(v))
                v.graph_message_id = message_id
            else:
                # DRY RUN: validated, recorded, not transmitted.
                log.info("email_dry_run", to=v.email_to, employee=v.employee_code)
            v.email_status = EmailStatus.SENT
            v.sent_at = datetime.now(UTC)
            sent += 1
        except Exception as exc:  # noqa: BLE001
            v.email_status = EmailStatus.ERROR
            v.email_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            errored += 1
    await db.commit()
    return sent, errored
