"""Track detached dataclasses within a single SQL transaction, without exposing ORM."""

from copy import deepcopy
from dataclasses import fields


class SnapshotTracker:
    def __init__(self):
        self._tracked = {}

    def track(self, row, state_type):
        if row is None:
            return None
        key = id(row), state_type
        if key not in self._tracked:
            state = state_type(**{
                field.name: deepcopy(getattr(row, field.name)) for field in fields(state_type)
            })
            self._tracked[key] = row, state
        return self._tracked[key][1]

    def synchronize(self):
        for row, state in self._tracked.values():
            for field in fields(state):
                value = deepcopy(getattr(state, field.name))
                if getattr(row, field.name) != value:
                    setattr(row, field.name, value)
