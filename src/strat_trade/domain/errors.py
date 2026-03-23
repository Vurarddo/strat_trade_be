from __future__ import annotations


class DomainError(Exception):
    """Base class for domain-level failures surfaced to the API layer."""


class BrokerUnavailableError(DomainError):
    """Broker could not be reached or rejected the session (timeouts, auth, etc.)."""

    def __init__(self, message: str, *, code: str = "BROKER_UNAVAILABLE") -> None:
        self.code = code
        super().__init__(message)


class InvalidMarketParametersError(DomainError):
    """Bad asset, timeframe, or range for a market-data request (broker rejected input)."""

    def __init__(self, message: str, *, code: str = "INVALID_MARKET_PARAMETERS") -> None:
        self.code = code
        super().__init__(message)


class UnknownIndicatorError(DomainError):
    """Requested indicator id is not registered."""

    def __init__(self, message: str, *, code: str = "UNKNOWN_INDICATOR") -> None:
        self.code = code
        super().__init__(message)


class IndicatorParameterError(DomainError):
    """Invalid parameters for a known indicator."""

    def __init__(self, message: str, *, code: str = "INDICATOR_PARAMETER_ERROR") -> None:
        self.code = code
        super().__init__(message)
