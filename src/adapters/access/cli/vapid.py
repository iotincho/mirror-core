"""Parse the explicit key-generation command; construction is provided by bootstrap."""

import argparse
from pathlib import Path


def main(generate_keys):
    parser = argparse.ArgumentParser(
        description="Generate VAPID files; do not overwrite existing keys"
    )
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    private, public = generate_keys(args.directory)
    print(f"Private key file: {private}\nPublic key file: {public}")
