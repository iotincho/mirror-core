"""Translate safe application codes to the existing public HTTP contract."""

from starlette.responses import JSONResponse


def invitation_status(code):
    if code in {"invitation_not_found", "subscription_not_found", "invitation_question_not_found"}:
        return 404
    if code in {
        "subscription_account_conflict",
        "idempotency_conflict",
        "active_subscription_required",
        "workspace_unavailable",
        "invitation_question_unavailable",
    }:
        return 409
    if code == "test_rate_limited":
        return 429
    if code == "web_push_not_configured":
        return 503
    return 422


async def invitation_error_handler(request, error):
    status = invitation_status(error.code)
    return JSONResponse(
        {"detail": error.code},
        status_code=status,
        headers={"Retry-After": "60"} if status == 429 else None,
    )


async def notification_error_handler(request, error):
    return JSONResponse(
        {"detail": error.code}, status_code=404 if error.code == "notification_not_found" else 422
    )
