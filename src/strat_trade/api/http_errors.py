from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from strat_trade.api.schemas import ErrorBody, ErrorEnvelope
from strat_trade.domain.errors import (
    BrokerUnavailableError,
    DomainError,
    InvalidMarketParametersError,
    LlmParsingError,
)


def register_domain_exception_handlers(app: FastAPI) -> None:
    """Map domain errors to the stable JSON error envelope."""

    @app.exception_handler(BrokerUnavailableError)
    async def broker_unavailable_handler(
        _request: Request,
        exc: BrokerUnavailableError,
    ) -> JSONResponse:
        body = ErrorEnvelope(error=ErrorBody(code=exc.code, message=str(exc))).model_dump()
        return JSONResponse(status_code=502, content=body)

    @app.exception_handler(InvalidMarketParametersError)
    async def invalid_market_parameters_handler(
        _request: Request,
        exc: InvalidMarketParametersError,
    ) -> JSONResponse:
        body = ErrorEnvelope(
            error=ErrorBody(code=exc.code, message=str(exc)),
        ).model_dump()
        return JSONResponse(status_code=400, content=body)

    @app.exception_handler(LlmParsingError)
    async def llm_parsing_handler(
        _request: Request,
        exc: LlmParsingError,
    ) -> JSONResponse:
        body = ErrorEnvelope(error=ErrorBody(code=exc.code, message=str(exc))).model_dump()
        return JSONResponse(status_code=502, content=body)

    @app.exception_handler(DomainError)
    async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
        code = getattr(exc, "code", "DOMAIN_ERROR")
        body = ErrorEnvelope(
            error=ErrorBody(code=code, message=str(exc)),
        ).model_dump()
        return JSONResponse(status_code=400, content=body)
