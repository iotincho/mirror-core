"""Compatibility import for callers that predate the user-management module."""

from src.user_management.authentication import COOKIE_NAME
from src.user_management.dependencies import get_authenticated_user as require_authenticated

__all__ = ["COOKIE_NAME", "require_authenticated"]
