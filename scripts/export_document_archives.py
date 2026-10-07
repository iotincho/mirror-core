"""Export every workspace's originals without SQL, ArcadeDB or application imports.

Can be mounted into an older API image before recreating any databases.
"""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

MAX_BYTES = 25 * 1024 * 1024


def export_all(root: Path, output: Path):
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Workspace directory is unavailable")
    if root.resolve() == output.resolve() or root.resolve() in output.resolve().parents:
        raise ValueError("Output must be outside the workspace directory")
    # Read and validate every archive before publishing any. Do not skip corrupt data.
    archives = {}
    for workspace in sorted(root.iterdir()):
        if workspace.is_symlink():
            raise ValueError("Symlinked workspace")
        if not workspace.is_dir():
            continue
        owner = str(UUID(workspace.name))
        directory = workspace / "documents"
        if directory.is_symlink():
            raise ValueError("Symlinked document directory")
        documents = []
        for file in sorted(directory.glob("*.json")):
            if file.is_symlink():
                raise ValueError("Symlinked document")
            doc = json.loads(file.read_text(encoding="utf-8"))
            if str(UUID(doc["id"])) != file.stem:
                raise ValueError("Document identity differs from filename")
            required = {"id", "content", "source", "metadata", "created_at"}
            if not required <= doc.keys() or doc.keys() - required - {"title", "authored_at"}:
                raise ValueError("Invalid original document fields")
            for key in ("content", "source"):
                if not isinstance(doc[key], str) or not doc[key].strip():
                    raise ValueError("Missing original document text or source")
            if not isinstance(doc["metadata"], dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in doc["metadata"].items()
            ):
                raise ValueError("Invalid document metadata")
            title = doc.get("title")
            if title is not None and (not isinstance(title, str) or not 1 <= len(title) <= 80):
                raise ValueError("Invalid document title")
            for key in ("created_at", "authored_at"):
                value = doc.get(key)
                if value is not None and datetime.fromisoformat(value).tzinfo is None:
                    raise ValueError("Document dates must include timezone")
            documents.append(doc)
        archive = {
            "format": "el-espejo-documents",
            "version": 1,
            "exported_at": datetime.now(UTC).isoformat(),
            "documents": documents,
        }
        payload = (json.dumps(archive, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(payload) > MAX_BYTES or len(documents) > 10000:
            raise ValueError("Archive exceeds import limits")
        archives[owner] = (payload, len(documents))
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for owner, (payload, _) in archives.items():
        path = output / f"{owner}.json"
        with path.open("xb") as file:
            os.chmod(path, 0o600)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
    return {owner: count for owner, (_, count) in archives.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(os.environ.get("WORKSPACES_PATH", "/data/workspaces"))
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export_all(args.root, args.output), indent=2))


if __name__ == "__main__":
    main()
