"""Compose public channel routers without loading HTTP composition in workers or CLIs."""

from src.adapters.access.api.public.activity import build_router as activity_router_factory
from src.adapters.access.api.public.invitations.routes import (
    build_router as invitation_router_factory,
)
from src.adapters.access.api.public.notifications import build_router as notification_router_factory
from src.bootstrap.activity import get_record_access
from src.bootstrap.auth import get_authenticated_user
from src.bootstrap.invitations import get_invitations
from src.bootstrap.notifications import get_notifications
from src.bootstrap.public_security import require_same_origin

activity_router = activity_router_factory(
    get_authenticated_user, get_record_access, require_same_origin,
)
invitation_router = invitation_router_factory(
    get_authenticated_user, get_invitations, require_same_origin,
)
notification_router = notification_router_factory(
    get_authenticated_user, get_notifications, require_same_origin,
)
