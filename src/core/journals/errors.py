"""Safe semantic failures; adapters choose their transport representation."""


class JournalError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
