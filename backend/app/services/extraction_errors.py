"""Safe extraction errors shared by parsers and format converters."""


class _ControlledExtractionError(Exception):
    """User-actionable rejection without provider output or filesystem details."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)
