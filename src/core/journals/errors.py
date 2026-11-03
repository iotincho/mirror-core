"""Safe semantic failures; adapters choose their transport representation."""


class JournalError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class JournalStorageUnavailable(RuntimeError):
    """The transaction was not confirmed; replay the same request key."""

    def __init__(self):
        super().__init__("journal_storage_unavailable")
