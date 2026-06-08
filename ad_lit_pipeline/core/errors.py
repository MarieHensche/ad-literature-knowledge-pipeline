from __future__ import annotations


class PipelineError(Exception):
    """Base exception for pipeline errors with user-facing context."""


class PipelinePause(PipelineError):
    """Raised when a pipeline step intentionally pauses for user input."""

    def __init__(self, message: str, result: object) -> None:
        super().__init__(message)
        self.result = result


class ValidationError(PipelineError):
    """Raised when an input artifact or config is invalid."""


class UnsupportedProviderError(PipelineError):
    """Raised when a selected provider has no implementation."""
