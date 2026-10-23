"""Safe workflow failure classification shared with providers."""

class WorkflowFailure(Exception):
    """Safe error code and retry decision supplied by the concrete use case."""

    def __init__(self, code: str, retry_delay: float | None = None, retryable: bool | None = None):
        super().__init__(code)
        self.code = code
        self.retry_delay = retry_delay
        self.retryable = retry_delay is not None if retryable is None else retryable


