from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from strat_trade.api.deps import CandleFeedDep, SignalRepositoryDep, get_settings
from strat_trade.api.schemas import ErrorBody, ErrorEnvelope
from strat_trade.settings import Settings
from strat_trade.use_cases.evaluate_pending_signals import EvaluatePendingSignalsUseCase

router = APIRouter(prefix="/jobs", tags=["Jobs"])


class EvaluateSignalsJobResponse(BaseModel):
    model_config = {"extra": "forbid"}

    signals_evaluated: int = Field(ge=0, description="Number of signals updated in this run.")
    status: str = Field(default="success", description="Job completion status.")


def _verify_job_secret(
    settings: Settings,
    x_job_secret: str | None,
) -> None:
    expected = (settings.job_api_secret or "").strip()
    if not expected:
        return
    got = (x_job_secret or "").strip()
    if got != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ErrorEnvelope(
                error=ErrorBody(
                    code="UNAUTHORIZED",
                    message="Invalid or missing X-Job-Secret.",
                )
            ).model_dump(),
        )


def require_job_auth(
    request: Request,
    x_job_secret: Annotated[str | None, Header(alias="X-Job-Secret")] = None,
) -> None:
    _verify_job_secret(get_settings(request), x_job_secret)


@router.post(
    "/evaluate-signals",
    response_model=EvaluateSignalsJobResponse,
    summary="Evaluate pending forward-test signals",
    operation_id="evaluatePendingSignalsJob",
    description=(
        "Cron-like job to resolve pending trades and calculate historical PnL. "
        "When `STRAT_TRADE_JOB_API_SECRET` is set, send matching header `X-Job-Secret`."
    ),
)
async def evaluate_signals_job(
    _auth: Annotated[None, Depends(require_job_auth)],
    signal_repository: SignalRepositoryDep,
    candle_feed: CandleFeedDep,
) -> EvaluateSignalsJobResponse:
    use_case = EvaluatePendingSignalsUseCase(
        signal_repository=signal_repository,
        candle_feed=candle_feed,
    )
    raw = await use_case.execute()
    return EvaluateSignalsJobResponse(
        signals_evaluated=int(raw["signals_evaluated"]),
        status=str(raw["status"]),
    )
