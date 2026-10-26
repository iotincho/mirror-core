"""Explicit notification catalog CLI; publication is always a requested command."""

from src.adapters.access.cli.announcements import main
from src.bootstrap.database import close_database
from src.bootstrap.notifications import get_notifications

if __name__ == "__main__":
    main(get_notifications, close_database)
