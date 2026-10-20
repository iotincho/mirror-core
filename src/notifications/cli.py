"""Preview/publish versioned announcements. Publication is explicit, never on startup."""

import argparse
import asyncio
import json
from pathlib import Path

from src.notifications.dependencies import get_notifications
from src.notifications.schemas import AnnouncementContent
from src.user_management.database import close_database


async def run(args):
    contents = [
        AnnouncementContent.model_validate(item) for item in json.loads(args.catalog.read_text())
    ]
    if len({item.key for item in contents}) != len(contents):
        raise ValueError("Duplicate publication keys")
    content = next((item for item in contents if item.key == args.key), None)
    if content is None:
        raise ValueError("Unknown publication key")
    try:
        repository = get_notifications()
        if args.command == "preview":
            print(
                json.dumps(
                    {
                        "content": content.model_dump(mode="json"),
                        "eligible_users": await repository.preview(),
                    },
                    ensure_ascii=False,
                )
            )
        else:
            await repository.publish(content)
            print("Publication recorded. The dispatcher will distribute it in restartable batches.")
    finally:
        await close_database()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["preview", "publish"])
    parser.add_argument("key")
    parser.add_argument(
        "--catalog", type=Path, default=Path(__file__).with_name("announcements.json")
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
