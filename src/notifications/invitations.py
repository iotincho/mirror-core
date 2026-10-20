"""Project the same invitation into the inbox, independently of push delivery."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.exteriorization.models import Invitation
from src.notifications.repository import add_notification


async def add_invitation_notification(session: AsyncSession, invitation: Invitation) -> None:
    await add_notification(
        session,
        owner=invitation.user_id,
        key=f"invitation:{invitation.id}",
        kind="invitation",
        title="Pregunta diaria de prueba" if invitation.kind == "test" else "Tu pregunta de hoy",
        summary=invitation.question,
        body=invitation.question,
        action={"type": "open_invitation", "invitation_id": str(invitation.id)},
        now=invitation.created_at,
        read_at=invitation.first_opened_at,
    )
