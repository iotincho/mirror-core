"""Explicit notification catalog CLI; publication is always a requested command."""

from src.adapters.access.cli.announcements import main as run
from src.bootstrap.database import close_database
from src.bootstrap.notifications import get_notifications


def main():
    run(get_notifications, close_database)


if __name__ == "__main__":
    main()
