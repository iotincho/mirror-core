"""Isolated HTTP fixture for PWA integration; never imported by production commands.

Run only against an empty disposable PostgreSQL database and RabbitMQ vhost/queue.
The /__tests__ controls belong exclusively to this fixture app, not src.main.app.
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi_users.password import PasswordHelper
from invitation_test_support import clock_path, controlled_now, invitation_repository
from pydantic import BaseModel
from sqlalchemy import delete, select, update

from src.adapters.storage.postgres.accounts import AccessToken, User
from src.adapters.storage.postgres.invitation_models import (
    Invitation,
    InvitationDelivery,
    InvitationPreference,
    InvitationResponse,
    PushSubscription,
)
from src.adapters.storage.postgres.workspace_models import UserWorkspace
from src.bootstrap.database import close_database, get_session_maker
from src.bootstrap.invitations import build_invitations, get_invitations
from src.bootstrap.workspaces import WorkspaceSecretCipher
from src.config import get_settings
from src.main import app as api
from src.processing.broker import broker
from src.processing.dispatcher import dispatch_once
from src.processing.models import (
    ProcessingEvent,
    ProcessingOutbox,
    ProcessingReceipt,
    ProcessingRecord,
)
from src.processing.runtime import get_repository
from src.processing.tasks import execute_processing
from src.use_cases.exteriorization.schedule_invitations import ScheduleInvitations

owners = [uuid4(), uuid4()]
password = "isolated-invitation-test-password"


@asynccontextmanager
async def lifespan(app):
    settings = get_settings()
    sessions = get_session_maker()
    async with sessions.begin() as session:
        for index, owner in enumerate(owners):
            session.add(
                User(
                    id=owner,
                    email=f"invitation-{index}-{owner}@example.com",
                    hashed_password=PasswordHelper().hash(password),
                )
            )
            await session.flush()
            session.add(
                UserWorkspace(
                    user_id=owner,
                    arcadedb_instance_key=settings.arcadedb_instance_key,
                    database_name=f"test_{owner.hex}",
                    graph_username=f"test_{owner.hex}",
                    graph_secret_ciphertext=WorkspaceSecretCipher(settings).encrypt(
                        "unused-test-secret"
                    ),
                    status="active",
                )
            )
            (settings.workspaces_path / str(owner) / "documents").mkdir(parents=True)
    api.dependency_overrides[get_invitations] = lambda: build_invitations(
        invitation_repository()
    )
    await broker.startup()
    try:
        yield
    finally:
        api.dependency_overrides.clear()
        async with sessions.begin() as session:
            for model in (
                InvitationResponse,
                InvitationDelivery,
                Invitation,
                PushSubscription,
                InvitationPreference,
                ProcessingReceipt,
                AccessToken,
            ):
                await session.execute(delete(model).where(model.user_id.in_(owners)))
            ids = select(ProcessingRecord.id).where(ProcessingRecord.user_id.in_(owners))
            await session.execute(
                delete(ProcessingOutbox).where(ProcessingOutbox.processing_id.in_(ids))
            )
            await session.execute(
                delete(ProcessingEvent).where(ProcessingEvent.user_id.in_(owners))
            )
            await session.execute(
                delete(ProcessingRecord).where(ProcessingRecord.user_id.in_(owners))
            )
            await session.execute(delete(UserWorkspace).where(UserWorkspace.user_id.in_(owners)))
            await session.execute(delete(User).where(User.id.in_(owners)))
        await broker.shutdown()
        await close_database()


app = FastAPI(lifespan=lifespan)
app.mount("/api", api)


@app.get("/__tests__/ready")
async def ready():
    return {
        "users": [
            {"id": str(owner), "email": f"invitation-{index}-{owner}@example.com"}
            for index, owner in enumerate(owners)
        ]
    }


class Tick(BaseModel):
    next_due: bool = False
    advance_seconds: int = 0
    duplicates: bool = False


@app.post("/__tests__/tick")
async def tick(payload: Tick):
    now = controlled_now()
    async with get_session_maker()() as session:
        if payload.next_due:
            preference = await session.get(InvitationPreference, owners[0])
            now = preference.next_due_at + timedelta(seconds=1)
        else:
            now += timedelta(seconds=payload.advance_seconds)
    temporary = clock_path().with_suffix(".tmp")
    temporary.write_text(now.isoformat())
    temporary.replace(clock_path())
    repository = get_repository()
    async with get_session_maker().begin() as session:
        # Advance only due push retries; never run the notes' existing extractors.
        ids = select(ProcessingRecord.id).where(
            ProcessingRecord.user_id.in_(owners),
            ProcessingRecord.workflow == "invitation_push",
            ProcessingRecord.status == "retrying",
        )
        from sqlalchemy import func

        await session.execute(
            update(ProcessingRecord)
            .where(ProcessingRecord.id.in_(ids))
            .values(available_at=func.now())
        )
        await session.execute(
            update(ProcessingOutbox)
            .where(ProcessingOutbox.processing_id.in_(ids))
            .values(available_at=func.now())
        )
    generated = await ScheduleInvitations(invitation_repository()).execute(now)

    async def publish(identifier, generation):
        record = await repository.get(UUID(identifier), owners[0])
        if record is None or record.workflow != "invitation_push":
            raise RuntimeError("non_push_work_is_outside_this_fixture")
        await execute_processing.kiq(identifier, generation)
        if payload.duplicates:
            await execute_processing.kiq(identifier, generation)

    await dispatch_once(repository, publish)
    return {"generated": generated, "now": now.isoformat()}


@app.get("/__tests__/snapshot")
async def snapshot():
    async with get_session_maker()() as session:
        invitations = (
            await session.scalars(
                select(Invitation).where(
                    Invitation.user_id.in_(owners),
                )
            )
        ).all()
        deliveries = (
            await session.scalars(
                select(InvitationDelivery).where(
                    InvitationDelivery.user_id.in_(owners),
                )
            )
        ).all()
        links = (
            await session.scalars(
                select(InvitationResponse).where(
                    InvitationResponse.user_id.in_(owners),
                )
            )
        ).all()
        jobs = (
            await session.scalars(
                select(ProcessingRecord).where(
                    ProcessingRecord.user_id.in_(owners),
                )
            )
        ).all()
        subscriptions = (
            await session.scalars(
                select(PushSubscription).where(
                    PushSubscription.user_id.in_(owners),
                )
            )
        ).all()
    captured = Path(os.environ["INVITATIONS_FLOW_DIRECTORY"]) / "push.jsonl"
    return {
        "invitations": [
            {
                "id": str(item.id),
                "question": item.question,
                "kind": item.kind,
                "opened": item.first_opened_at is not None,
            }
            for item in invitations
        ],
        "deliveries": [{"status": item.status, "attempts": item.attempts} for item in deliveries],
        "links": [
            {"document_id": str(item.document_id), "invitation_id": str(item.invitation_id)}
            for item in links
        ],
        "jobs": [
            {
                "id": str(item.id),
                "workflow": item.workflow,
                "status": item.status,
                "extractors": [part["name"] for part in item.config.get("extractors", [])],
            }
            for item in jobs
        ],
        "subscriptions": [
            {"active": item.active, "binding_id": str(item.binding_id)} for item in subscriptions
        ],
        "captured": [json.loads(line) for line in captured.read_text().splitlines()]
        if captured.exists()
        else [],
    }
