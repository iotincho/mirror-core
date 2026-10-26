"""Generate a VAPID pair into private files, never into application logs."""

import base64
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key


def generate_keys(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_path, public_path = directory / "private.pem", directory / "public.txt"
    if private_path.exists() or public_path.exists():
        raise FileExistsError("VAPID files already exist")
    private_key = generate_private_key(SECP256R1())
    private = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public = (
        base64.urlsafe_b64encode(
            private_key.public_key().public_bytes(
                serialization.Encoding.X962,
                serialization.PublicFormat.UncompressedPoint,
            )
        )
        .decode()
        .rstrip("=")
    )
    # Exclusive creation prevents accidentally rotating an already deployed pair.
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(private)
    with public_path.open("x", encoding="utf-8") as stream:
        stream.write(public + "\n")
    return private_path, public_path
