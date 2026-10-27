"""Protect public mutations using exact origins and the browser fetch context."""

from urllib.parse import urlsplit

from fastapi import HTTPException, Request


def same_origin(allowed_origins):
    async def require_same_origin(request: Request) -> None:
        if request.method in {"GET", "HEAD", "OPTIONS"}:
            return
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "cross_origin_request")
        if origin:
            parsed = urlsplit(origin)
            allowed = allowed_origins()
            if origin not in allowed and (
                parsed.scheme != request.url.scheme or parsed.netloc != request.url.netloc
            ):
                raise HTTPException(403, "cross_origin_request")
        # SameSite=Strict + JSON bodies/custom idempotency header protect requests
        # without Origin (native clients). No credentialed CORS is enabled.

    return require_same_origin
