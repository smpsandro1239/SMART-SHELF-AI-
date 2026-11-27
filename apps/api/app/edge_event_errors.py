"""Shared errors for Edge event processing and domain handlers."""


class EdgeEventHandlerError(RuntimeError):
    """A handler failure with an explicit retry policy."""

    def __init__(self, code: str, *, retryable: bool = True):
        super().__init__(code)
        self.code = code
        self.retryable = retryable
