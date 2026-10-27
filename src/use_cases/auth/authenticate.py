"""Verify a password under the account lock shared with password recovery."""

from src.core.auth.ports import AuthenticationAccounts, Passwords


class AuthenticateUser:
    def __init__(self, accounts: AuthenticationAccounts, passwords: Passwords):
        self.accounts, self.passwords = accounts, passwords

    async def execute(self, email: str, password: str):
        account = await self.accounts.credentials(email)
        if account is None:
            self.passwords.hash(password)
            return None
        verified, upgraded_hash = self.passwords.verify_and_update(
            password, account.hashed_password
        )
        if not verified:
            return None
        changes = {}
        if upgraded_hash is not None:
            changes["hashed_password"] = upgraded_hash
        if account.password_login_enabled is not True:
            changes["password_login_enabled"] = True
        if changes:
            await self.accounts.confirm_login(account, changes)
        return account
