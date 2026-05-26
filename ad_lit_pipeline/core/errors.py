from __future__ import annotations


class PipelineError(Exception):
    """Base exception for pipeline errors with user-facing context."""


class ValidationError(PipelineError):
    """Raised when an input artifact or config is invalid."""


class UnsupportedProviderError(PipelineError):
    """Raised when a selected provider has no implementation."""

