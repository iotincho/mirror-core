from src.notifications.repository import NotificationRepository
from src.user_management.database import get_session_maker


def get_notifications():
    return NotificationRepository(get_session_maker())
