"""Explicit errors used to prevent silent safety fallbacks."""

from __future__ import annotations


class ReviewTriageError(Exception):
    """Base class for controlled workflow failures."""


class InvalidInputError(ReviewTriageError):
    """NODE-00 rejected malformed or incomplete input."""


class LLMProcessingError(ReviewTriageError):
    """An LLM call, JSON parse, or output schema validation failed."""

    def __init__(self, code: str, message: str, *, node_name: str) -> None:
        super().__init__(message)
        self.code = code
        self.node_name = node_name


class PolicyConfigurationError(ReviewTriageError):
    """Frozen reliability policy data is absent, incomplete, or inconsistent."""
