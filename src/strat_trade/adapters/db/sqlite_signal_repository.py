from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, and_, delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from strat_trade.domain.trade_record import TradeSignalRecord
from strat_trade.ports.signal_repository import SignalRepository

Base = declarative_base()


class SignalModel(Base):
    __tablename__ = "trade_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    asset = Column(String(50), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    direction = Column(String(20), nullable=False)
    entry_price = Column(Float, nullable=False)
    expiration_in_seconds = Column(Integer, nullable=False)
    expected_close_time = Column(DateTime(timezone=True), nullable=False)
    strategy_name = Column(String(100), nullable=False)
    win_probability_percentage = Column(Integer, nullable=False)

    is_resolved = Column(Boolean, default=False, nullable=False)
    actual_close_price = Column(Float, nullable=True)
    pnl_result = Column(String(20), nullable=True)
    broker_trade_id = Column(String(100), nullable=True)


engine = create_async_engine("sqlite+aiosqlite:///./forward_test.db", echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class SqliteSignalRepository(SignalRepository):
    """SQLAlchemy adapter for SQLite storage of trade signals."""

    async def save_signal(self, record: TradeSignalRecord) -> TradeSignalRecord:
        async with AsyncSessionLocal() as session:
            model = SignalModel(
                asset=record.asset,
                timestamp=record.timestamp,
                direction=record.direction,
                entry_price=record.entry_price,
                expiration_in_seconds=record.expiration_in_seconds,
                expected_close_time=record.expected_close_time,
                strategy_name=record.strategy_name,
                win_probability_percentage=record.win_probability_percentage,
                is_resolved=record.is_resolved,
                actual_close_price=record.actual_close_price,
                pnl_result=record.pnl_result,
                broker_trade_id=record.broker_trade_id,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)

            record.id = model.id
            return record

    async def get_recent_signals(self, limit: int = 50) -> list[TradeSignalRecord]:
        async with AsyncSessionLocal() as session:
            stmt = select(SignalModel).order_by(desc(SignalModel.timestamp)).limit(limit)
            result = await session.execute(stmt)
            models = result.scalars().all()

            records = []
            for model in models:
                # Ensure timezone awareness matches Python logic due to naive SQLite drivers.
                ts = model.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)

                close_ts = model.expected_close_time
                if close_ts.tzinfo is None:
                    close_ts = close_ts.replace(tzinfo=UTC)

                record = TradeSignalRecord(
                    id=model.id,
                    asset=model.asset,
                    timestamp=ts,
                    direction=model.direction,
                    entry_price=model.entry_price,
                    expiration_in_seconds=model.expiration_in_seconds,
                    expected_close_time=close_ts,
                    strategy_name=model.strategy_name,
                    win_probability_percentage=model.win_probability_percentage,
                    is_resolved=model.is_resolved,
                    actual_close_price=model.actual_close_price,
                    pnl_result=model.pnl_result,
                    broker_trade_id=model.broker_trade_id,
                )
                records.append(record)

            return records

    async def get_unresolved_signals(self, up_to_time: datetime) -> list[TradeSignalRecord]:
        async with AsyncSessionLocal() as session:
            stmt = (
                select(SignalModel)
                .where(
                    and_(
                        SignalModel.is_resolved.is_(False),
                        SignalModel.expected_close_time <= up_to_time,
                    )
                )
                .order_by(SignalModel.expected_close_time)
            )
            result = await session.execute(stmt)
            models = result.scalars().all()

            records: list[TradeSignalRecord] = []
            for model in models:
                ts = model.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)

                close_ts = model.expected_close_time
                if close_ts.tzinfo is None:
                    close_ts = close_ts.replace(tzinfo=UTC)

                records.append(
                    TradeSignalRecord(
                        id=model.id,
                        asset=model.asset,
                        timestamp=ts,
                        direction=model.direction,
                        entry_price=model.entry_price,
                        expiration_in_seconds=model.expiration_in_seconds,
                        expected_close_time=close_ts,
                        strategy_name=model.strategy_name,
                        win_probability_percentage=model.win_probability_percentage,
                        is_resolved=model.is_resolved,
                        actual_close_price=model.actual_close_price,
                        pnl_result=model.pnl_result,
                    )
                )
            return records

    async def delete_signal(self, signal_id: int) -> bool:
        async with AsyncSessionLocal() as session:
            result = await session.execute(delete(SignalModel).where(SignalModel.id == signal_id))
            await session.commit()
            return (result.rowcount or 0) > 0

    async def update_signal_resolution(
        self, signal_id: int, actual_close_price: float, pnl_result: str
    ) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SignalModel)
                .where(SignalModel.id == signal_id)
                .values(
                    actual_close_price=actual_close_price,
                    pnl_result=pnl_result,
                    is_resolved=True,
                )
            )
            await session.commit()

    async def has_unresolved_signal(self, asset: str) -> bool:
        async with AsyncSessionLocal() as session:
            stmt = select(SignalModel).where(
                and_(
                    SignalModel.asset == asset,
                    SignalModel.is_resolved.is_(False)
                )
            ).limit(1)
            result = await session.execute(stmt)
            return result.first() is not None

    async def get_trade_statistics(self) -> dict:
        async with AsyncSessionLocal() as session:
            stmt = select(SignalModel).where(SignalModel.is_resolved.is_(True))
            result = await session.execute(stmt)
            models = result.scalars().all()
            
            stats = {
                "total_trades": len(models),
                "total_won_trades": 0,
                "total_loss_trades": 0,
                "total_tied_trades": 0
            }
            
            for model in models:
                if model.pnl_result == "WIN":
                    stats["total_won_trades"] += 1
                elif model.pnl_result == "LOSS":
                    stats["total_loss_trades"] += 1
                elif model.pnl_result == "TIE":
                    stats["total_tied_trades"] += 1
                    
            return stats

