"""Safe workflow failure classification shared with providers."""


class WorkflowFailure(Exception):
    """Safe error code and retry decision supplied by the concrete use case."""

    def __init__(self, code: str, retry_delay: float | None = None, retryable: bool | None = None):
        super().__init__(code)
        self.code = code
        self.retry_delay = retry_delay
        self.retryable = retry_delay is not None if retryable is None else retryable


class LeaseLost(RuntimeError):
    """An expired or replaced worker may no longer commit progress."""


class ResourceBusy(RuntimeError):
    pass


class StorageUnavailable(RuntimeError):
    """State was not durably resolved; keep delivery unacknowledged for recovery."""


class WorkflowWaiting(Exception):
    """The workflow durably handed execution to its children."""


class FailureDecision:
    """A classified failure may suppress provider context to preserve source privacy."""

    def __init__(self, failure: WorkflowFailure, *, suppress_cause=False):
        self.failure = failure
        self.suppress_cause = suppress_cause
