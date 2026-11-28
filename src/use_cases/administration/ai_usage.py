"""Administrative usage queries for the selected period and account."""

from src.core.administration.ai_usage_queries import AiUsageQueries
from src.use_cases.administration.query import Administration, AdministrationError


class AiUsageAdministration:
    def __init__(self, queries: AiUsageQueries):
        self.queries = queries

    async def summary(self, days, user_id):
        result = await self.queries.summary(Administration.period(days), user_id)
        if result is None:
            raise AdministrationError("user_not_found")
        return result

    async def ranking(self, days, page, per_page):
        return await self.queries.ranking(Administration.period(days), page, per_page)
