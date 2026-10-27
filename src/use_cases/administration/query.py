"""Administrative query/permission actions, independent of HTTP and SQL sessions."""

from src.core.administration.ports import AdministrationQueries
from src.core.administration.rules import activity_series, dashboard_summary


class AdministrationError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class Administration:
    def __init__(self, queries: AdministrationQueries):
        self.queries = queries

    async def list_users(self, page, per_page, sort, order, q, is_active):
        return await self.queries.list_users(page, per_page, sort, order, q.strip(), is_active)

    async def user(self, user_id):
        result = await self.queries.user(user_id)
        if result is None:
            raise AdministrationError("user_not_found")
        return result

    async def set_laboratory_access(self, user_id, enabled):
        result = await self.queries.save_laboratory_access(user_id, enabled)
        if result is None:
            raise AdministrationError("user_not_found")
        return result

    @staticmethod
    def period(days):
        if days not in (7, 30):
            raise AdministrationError("period_days must be 7 or 30")
        return days

    async def summary(self, days):
        facts = await self.queries.summary(self.period(days))
        return dashboard_summary(facts, days)

    async def activity(self, days):
        facts = await self.queries.activity(self.period(days))
        return activity_series(facts, days)
