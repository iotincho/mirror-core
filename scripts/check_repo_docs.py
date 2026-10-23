"""Check documentation links, index coverage and agent instruction budgets.

Standard library only; never reads application configuration or contacts services.
Checks repository documentation without requiring sibling repository checkouts.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ROOT_BUDGET = 6 * 1024
AREA_BUDGET = 3 * 1024
CHAIN_BUDGET = 12 * 1024
INLINE_LINK = re.compile(r"\[[^\]\n]*\]\(([^)\n]+)\)")
CODE_FENCE = re.compile(r"^```[^\n]*\n.*?^```\s*$", re.MULTILINE | re.DOTALL)


def local_targets(path: Path) -> list[Path]:
    """Return local inline-link targets, omitting code fences and URL fragments."""
    content = CODE_FENCE.sub("", path.read_text(encoding="utf-8"))
    targets = []
    for raw in INLINE_LINK.findall(content):
        url = urlsplit(raw.strip().strip("<>"))
        if url.scheme or url.netloc or not url.path:
            continue
        targets.append((path.parent / unquote(url.path)).resolve())
    return targets


def main() -> int:
    instructions = [ROOT / "AGENTS.md"]
    for directory in ("src", "tests", "migrations", "scripts", "docs"):
        instructions.extend(sorted((ROOT / directory).rglob("AGENTS.md")))
    maintained = sorted(
        {
            ROOT / "README.md",
            ROOT / "src/graph/README.md",
            *instructions,
            *(ROOT / "docs").rglob("*.md"),
        }
    )
    errors = []
    linked = set()
    for path in maintained:
        if not path.is_file():
            errors.append(f"missing entry point: {path.relative_to(ROOT)}")
            continue
        for target in local_targets(path):
            if not target.is_relative_to(ROOT) or not target.exists():
                errors.append(f"{path.relative_to(ROOT)}: invalid local target {target}")
            if path == ROOT / "docs/README.md":
                linked.add(target)

    for path in sorted((ROOT / "docs").glob("*.md")):
        if path.name != "README.md" and path not in linked:
            errors.append(f"not indexed: {path.relative_to(ROOT)}")

    sizes = {path: path.stat().st_size for path in instructions if path.is_file()}
    longest = 0
    for path, size in sizes.items():
        limit = ROOT_BUDGET if path == ROOT / "AGENTS.md" else AREA_BUDGET
        if size > limit:
            errors.append(f"{path.relative_to(ROOT)}: {size} bytes exceeds {limit}")
        chain = sum(
            parent_size
            for parent, parent_size in sizes.items()
            if path.parent.is_relative_to(parent.parent)
        )
        longest = max(longest, chain)
        if chain > CHAIN_BUDGET:
            errors.append(f"{path.relative_to(ROOT)}: instruction chain exceeds {CHAIN_BUDGET}")

    if errors:
        print("\n".join(errors))
        return 1
    print(f"OK: {len(maintained)} entry points; local links and documentation index checked.")
    print(
        f"Instructions: root={sizes[ROOT / 'AGENTS.md']} bytes; "
        f"longest chain={longest}/{CHAIN_BUDGET} bytes; "
        f"{len(instructions)} files (not all loaded together)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
