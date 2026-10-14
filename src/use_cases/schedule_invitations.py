"""Periodic adapter invokes this durable scheduler; database locks arbitrate replicas."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from src.exteriorization.models import Invitation, InvitationPreference, PushSubscription
from src.exteriorization.repository import InvitationRepository
from src.exteriorization.scheduling import expires_at, next_occurrence, scheduled_at
from src.use_cases.generate_invitation import GenerateInvitation
from src.workspaces.models import UserWorkspace


class ScheduleInvitations:
    def __init__(self, repository: InvitationRepository) -> None:
        self.repository = repository

    async def execute(self, now: datetime | None = None) -> int:
        async with self.repository.sessions.begin() as session:
            now = now or await self.repository.now(session)
            await self.repository.reconcile_deliveries(session, now)
        async with self.repository.sessions.begin() as session:
            preferences = (
                await session.scalars(
                    select(InvitationPreference)
                    .where(
                        InvitationPreference.enabled.is_(True),
                        InvitationPreference.next_due_at <= now,
                    )
                    .order_by(InvitationPreference.next_due_at)
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            generated = 0
            for preference in preferences:
                due = preference.next_due_at
                preference.next_due_at = next_occurrence(
                    now,
                    preference.local_time,
                    preference.timezone,
                )
                preference.updated_at = now
                today = now.astimezone(ZoneInfo(preference.timezone)).date()
                if due.astimezone(ZoneInfo(preference.timezone)).date() < today:
                    # A long outage must not hide today's still-eligible occurrence.
                    due = scheduled_at(today, preference.local_time, preference.timezone)
                    if due > now:
                        continue
                if now >= expires_at(due, preference.timezone):
                    continue
                active = await session.scalar(
                    select(UserWorkspace.user_id).where(
                        UserWorkspace.user_id == preference.user_id,
                        UserWorkspace.status == "active",
                    )
                )
                if active is None:
                    continue
                subscriptions = list(
                    (
                        await session.scalars(
                            select(PushSubscription)
                            .where(
                                PushSubscription.user_id == preference.user_id,
                                PushSubscription.active.is_(True),
                            )
                            .order_by(PushSubscription.id)
                            .with_for_update()
                        )
                    ).all()
                )
                if not subscriptions:
                    continue
                day = due.astimezone(ZoneInfo(preference.timezone)).date()
                existing = await session.scalar(
                    select(Invitation.id).where(
                        Invitation.user_id == preference.user_id,
                        Invitation.kind == "scheduled",
                        Invitation.local_date == day,
                    )
                )
                if existing is None:
                    await GenerateInvitation().execute(session, preference, due, now, subscriptions)
                    generated += 1
            return generated
