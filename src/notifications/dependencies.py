from src.bootstrap.database import get_session_maker
from src.notifications.repository import NotificationRepository


def get_notifications():
    return NotificationRepository(get_session_maker())
