"""Plan local-date occurrences; persistence locks arbitrate concurrent dispatchers."""

from zoneinfo import ZoneInfo

from src.core.exteriorization.ports import Invitations
from src.core.exteriorization.scheduling import expires_at, next_occurrence, scheduled_at
from src.use_cases.exteriorization.generate_invitation import GenerateInvitation


class ScheduleInvitations:
    def __init__(self, repository: Invitations, personalization=None, policy=None):
        self.repository = repository
        self.generator = GenerateInvitation(personalization, policy)

    async def execute(self, now=None):
        async with self.repository.transaction() as transaction:
            now = now or await transaction.now()
            await transaction.reconcile_deliveries(now)
        async with self.repository.transaction() as transaction:
            generated = 0
            for preference in await transaction.due_preferences(now):
                due = preference.next_due_at
                preference_version = preference.updated_at
                preference.next_due_at = next_occurrence(
                    now, preference.local_time, preference.timezone
                )
                preference.updated_at = now
                today = now.astimezone(ZoneInfo(preference.timezone)).date()
                if due.astimezone(ZoneInfo(preference.timezone)).date() < today:
                    due = scheduled_at(today, preference.local_time, preference.timezone)
                    if due > now:
                        continue
                if now >= expires_at(due, preference.timezone):
                    continue
                if not await transaction.workspace_active(preference.user_id):
                    continue
                subscriptions = await transaction.active_subscriptions(preference.user_id)
                day = due.astimezone(ZoneInfo(preference.timezone)).date()
                if not await transaction.scheduled_exists(preference.user_id, day):
                    invitation = await self.generator.execute(
                        transaction,
                        preference,
                        due,
                        now,
                        subscriptions,
                        preference_version=preference_version,
                    )
                    if invitation is None:
                        await transaction.omit_occurrence(preference.user_id, day, now)
                    else:
                        generated += 1
            return generated
