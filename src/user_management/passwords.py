"""One password policy shared by signup and password recovery."""

from fastapi_users import exceptions


def validate_password(password: str, email: str) -> None:
    if len(password) < 12:
        raise exceptions.InvalidPasswordException(
            reason="Password should be at least 12 characters"
        )
    if email.lower() in password.lower():
        raise exceptions.InvalidPasswordException(
            reason="Password should not contain the email address"
        )
