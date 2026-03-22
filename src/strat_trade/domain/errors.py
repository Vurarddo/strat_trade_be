from __future__ import annotations


class DomainError(Exception):
    """Base class for domain-level failures surfaced to the API layer."""


class BrokerUnavailableError(DomainError):
    """Broker could not be reached or rejected the session (timeouts, auth, etc.)."""

    def __init__(self, message: str, *, code: str = "BROKER_UNAVAILABLE") -> None:
        self.code = code
        super().__init__(message)
