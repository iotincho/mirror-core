"""Bounded rotating scans of temporary preview directories, without time policy."""

import asyncio
from uuid import UUID

from src.adapters.storage.filesystem.personal_axes.previews import PreviewFiles
from src.core.extractors.personal_axes.previews import PreviewLocation

_cursors = {}


class PreviewRoots:
    def __init__(self, root):
        self._root = root

    def for_owner(self, owner):
        return PreviewFiles(self._root / str(owner))

    async def candidates(self, limit):
        return await asyncio.to_thread(self._candidates, limit)

    def _candidates(self, limit):
        if not self._root.exists():
            return []
        cursor, checked, result = _cursors.get(str(self._root), ""), 0, []
        for directory in sorted(self._root.glob("*/laboratory/previews/*")):
            if str(directory) <= cursor:
                continue
            if checked >= limit:
                break
            checked += 1
            _cursors[str(self._root)] = str(directory)
            try:
                result.append(
                    PreviewLocation(UUID(directory.parents[2].name), UUID(directory.name))
                )
            except ValueError:
                continue
        if checked < limit:
            _cursors.pop(str(self._root), None)
        return result
