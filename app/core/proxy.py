"""Client address behind reverse proxies.

Each proxy appends its peer address to X-Forwarded-For, so only the right-most entries are
trustworthy; anything further left is client-controlled. TRUSTED_PROXY_HOPS is the number of
proxies in front of the API (0 direct, 1 Render LB or nginx, 2 Vercel rewrite -> Render). Taking
the entry that many places from the right means a forged header can never change the address
used for rate limits and the audit log.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send


def client_from_forwarded(header: str, hops: int) -> str | None:
    entries = [e.strip() for e in header.split(",") if e.strip()]
    if hops <= 0 or not entries:
        return None
    return entries[-min(hops, len(entries))]


class TrustedProxyMiddleware:
    def __init__(self, app: ASGIApp, hops: int) -> None:
        self.app = app
        self.hops = hops

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.hops > 0:
            forwarded_for = ", ".join(
                v.decode("latin1") for k, v in scope["headers"] if k == b"x-forwarded-for"
            )
            host = client_from_forwarded(forwarded_for, self.hops)
            if host:
                port = scope["client"][1] if scope.get("client") else 0
                scope = dict(scope, client=(host, port))
            for k, v in scope["headers"]:
                if k == b"x-forwarded-proto":
                    proto = v.decode("latin1").split(",")[-1].strip()
                    if proto in ("http", "https"):
                        scope = dict(scope, scheme=proto)
                    break
        await self.app(scope, receive, send)
