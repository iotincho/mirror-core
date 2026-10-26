"""Global availability, account grant and welcome preference without workspace/provider access."""

from src.core.extractors.personal_axes.models import AxisError
from src.core.extractors.personal_axes.ports import LaboratoryAccounts


class Laboratory:
    def __init__(self, accounts: LaboratoryAccounts, enabled: bool):
        self.accounts, self.enabled = accounts, enabled

    async def available(self, owner):
        if not self.enabled:
            return False
        state = await self.accounts.read(owner)
        return state.active and state.granted

    async def require_access(self, owner):
        if not await self.available(owner):
            raise AxisError("axis_access_disabled")

    async def context(self, owner):
        state = await self.accounts.read(owner)
        return {
            "enabled": self.enabled and state.active and state.granted,
            "welcome_dismissed": state.welcome_dismissed,
        }

    async def dismiss_welcome(self, owner):
        await self.accounts.dismiss_welcome(owner)
        return {"welcome_dismissed": True}
