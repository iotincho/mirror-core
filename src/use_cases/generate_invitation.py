"""Persist a single selected question and its device jobs in one transaction."""

from datetime import datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.exteriorization.contracts import EngineContext, Trigger
from src.exteriorization.engine import select_trigger
from src.exteriorization.models import (
    Invitation,
    InvitationDelivery,
    InvitationPreference,
    PushSubscription,
)
from src.exteriorization.scheduling import expires_at
from src.processing.models import ProcessingRecord
from src.processing.repository import ProcessingRepository


class GenerateInvitation:
    async def execute(
        self,
        session: AsyncSession,
        preference: InvitationPreference,
        due: datetime,
        now: datetime,
        subscriptions: list[PushSubscription],
        *,
        request_key: UUID | None = None,
    ) -> Invitation:
        kind = "test" if request_key else "scheduled"
        history = (
            await session.scalars(
                select(Invitation)
                .where(
                    Invitation.user_id == preference.user_id,
                    Invitation.kind == "scheduled",
                )
                .order_by(Invitation.created_at.desc(), Invitation.id.desc())
                .limit(7)
            )
        ).all()
        trigger = select_trigger(
            EngineContext(
                now=now,
                timezone=preference.timezone,
                history=tuple(
                    Trigger(**{field: getattr(item, field) for field in Trigger.model_fields})
                    for item in history
                ),
            )
        )
        day = due.astimezone(ZoneInfo(preference.timezone)).date()
        invitation = Invitation(
            id=uuid4(),
            user_id=preference.user_id,
            kind=kind,
            local_date=day,
            timezone=preference.timezone,
            scheduled_at=due,
            expires_at=expires_at(due, preference.timezone)
            if kind == "scheduled"
            else now + timedelta(minutes=5),
            occurrence_key=f"{preference.user_id}:{day}"
            if kind == "scheduled"
            else f"test:{preference.user_id}:{request_key}",
            request_key=request_key,
            test_subscription_id=subscriptions[0].id if request_key else None,
            created_at=now,
            **trigger.model_dump(),
        )
        session.add(invitation)
        await session.flush()
        for subscription in subscriptions:
            delivery_id = uuid4()
            record = ProcessingRecord(
                id=uuid4(),
                user_id=preference.user_id,
                workflow="invitation_push",
                workflow_version=1,
                stage="push_send",
                resource_kind="invitation_delivery",
                resource_id=delivery_id,
                config={},
            )
            session.add(record)
            await session.flush()
            session.add(
                InvitationDelivery(
                    id=delivery_id,
                    user_id=preference.user_id,
                    invitation_id=invitation.id,
                    subscription_id=subscription.id,
                    processing_id=record.id,
                    status="pending",
                    next_attempt_at=now,
                )
            )
            ProcessingRepository.schedule(session, record)
        return invitation
