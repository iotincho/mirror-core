"""Password policy shared by registration and recovery, independent of frameworks."""


class InvalidPassword(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_password(password: str, email: str) -> None:
    if len(password) < 12:
        raise InvalidPassword("Password should be at least 12 characters")
    if email.lower() in password.lower():
        raise InvalidPassword("Password should not contain the email address")
