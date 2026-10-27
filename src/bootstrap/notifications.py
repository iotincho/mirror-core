"""Compose the inbox and announcement actions used by HTTP, CLI and dispatcher."""

from src.adapters.storage.postgres.notifications import PostgresNotifications
from src.bootstrap.database import get_session_maker
from src.use_cases.notifications.center import NotificationCenter


def build_notification_center(sessions):
    return NotificationCenter(PostgresNotifications(sessions))


def get_notifications():
    return build_notification_center(get_session_maker())
