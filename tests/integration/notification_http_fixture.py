"""Local cross-repository fixture: real cookie auth/API/SQL; workspace provisioning stubbed.

Only run with DATABASE_URL == NOTIFICATIONS_TEST_DATABASE_URL on an isolated database.
No dispatcher, graph, model provider or push transport is started.
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import delete, select

from src.api.router import api_router
from src.exteriorization.models import Invitation, InvitationPreference
from src.exteriorization.repository import InvitationRepository
from src.notifications.dependencies import get_notifications
from src.notifications.models import Announcement
from src.notifications.schemas import AnnouncementContent
from src.use_cases.configure_invitations import ConfigureInvitations
from src.use_cases.schedule_invitations import ScheduleInvitations
from src.user_management.database import close_database, get_session_maker
from src.user_management.models import AccessToken, User
from src.workspaces.models import UserWorkspace


@asynccontextmanager
async def lifespan(app):
    assert os.environ["DATABASE_URL"] == os.environ["NOTIFICATIONS_TEST_DATABASE_URL"]
    marker = Path(os.environ["NOTIFICATIONS_FLOW_MARKER"])
    owner, token = uuid4(), uuid4().hex
    key = f"fixture-{owner.hex}"
    sessions = get_session_maker()
    try:
        async with sessions.begin() as session:
            session.add(User(id=owner, email=f"{owner}@example.com", hashed_password="unused"))
            await session.flush()
            session.add(AccessToken(token=token, user_id=owner))
            session.add(
                UserWorkspace(
                    user_id=owner,
                    arcadedb_instance_key="fixture",
                    database_name=f"test_{owner.hex}",
                    graph_username=f"test_{owner.hex}",
                    graph_secret_ciphertext="unused",
                    status="active",
                )
            )
        repository = get_notifications()
        await repository.bootstrap(owner)
        invitations = InvitationRepository(sessions)
        await ConfigureInvitations(invitations).configure(owner, True, "20:30", "UTC")
        now = datetime.now(UTC)
        async with sessions.begin() as session:
            preference = await session.get(InvitationPreference, owner)
            preference.local_time = now.strftime("%H:%M")
            preference.next_due_at = now - timedelta(seconds=1)
        await ScheduleInvitations(invitations).execute(now)
        await repository.publish(
            AnnouncementContent(
                key=key,
                title="Una mejora de integración",
                summary="API y bandeja conectadas",
                body="Esta novedad viene de PostgreSQL y de la API real, sin simular la bandeja.",
            )
        )
        await repository.distribute()
        async with sessions() as session:
            invitation_id = await session.scalar(
                select(Invitation.id).where(
                    Invitation.user_id == owner, Invitation.kind == "scheduled"
                )
            )
        marker.write_text(
            json.dumps({"user_id": str(owner), "token": token, "invitation_id": str(invitation_id)})
        )
        marker.chmod(0o600)
        yield
    finally:
        marker.unlink(missing_ok=True)
        async with sessions.begin() as session:
            await session.execute(delete(Invitation).where(Invitation.user_id == owner))
            await session.execute(delete(Announcement).where(Announcement.key == key))
            await session.execute(delete(User).where(User.id == owner))
        await close_database()


app = FastAPI(lifespan=lifespan)


@app.get("/workspace/status")
def provisioned_workspace():
    # Only the external workspace readiness check is stubbed. Identity and all inbox
    # endpoints use the real cookie strategy and the explicit isolated PostgreSQL.
    return {"status": "active"}


app.include_router(api_router)
