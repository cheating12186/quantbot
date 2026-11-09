"""Repository conversions, portfolio snapshots, run history, and journals."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from config.settings import RiskConfig
from database.db import Database
from database.models import (
    AccountRecord,
    AgentTraceRecord,
    EquityRecord,
    FillRecord,
    JournalRecord,
    OrderRecord,
    PositionRecord,
    RunRecord,
)
from models.agent_outputs import AgentTrace, FinalReport
from models.portfolio import PortfolioSnapshot
from models.trade import Fill, Order, Position, ResearchRequest


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class Repository:
    def __init__(self, database: Database, risk: RiskConfig):
        self.db = database
        self.risk = risk

    def ensure_account(self) -> None:
        with self.db.session() as session:
            if session.get(AccountRecord, 1) is None:
                equity = self.risk.default_equity
                session.add(AccountRecord(id=1, cash=equity, equity=equity, initial_equity=equity, day_start_equity=equity, high_water_mark=equity))

    @staticmethod
    def to_position(record: PositionRecord) -> Position:
        return Position(
            position_id=record.position_id, symbol=record.symbol, side=record.side, quantity=record.quantity,
            entry_price=record.entry_price, stop_loss=record.stop_loss, take_profit=record.take_profit,
            opened_at=aware(record.opened_at), mark_price=record.mark_price, realized_pnl=record.realized_pnl,
            entry_fees=getattr(record, "entry_fees", 0.0),
        )

    @staticmethod
    def to_order(record: OrderRecord) -> Order:
        return Order(
            order_id=record.order_id, client_order_id=record.client_order_id, run_id=record.run_id,
            symbol=record.symbol, side=record.side, order_type=record.order_type, quantity=record.quantity,
            limit_price=record.limit_price, stop_loss=record.stop_loss, take_profit=record.take_profit,
            status=record.status, filled_quantity=record.filled_quantity, average_fill_price=record.average_fill_price,
            fees=record.fees, created_at=aware(record.created_at), updated_at=aware(record.updated_at),
            rejection_reason=record.rejection_reason,
        )

    @staticmethod
    def to_fill(record: FillRecord) -> Fill:
        return Fill(
            fill_id=record.fill_id, order_id=record.order_id, symbol=record.symbol, side=record.side,
            quantity=record.quantity, price=record.price, fees=record.fees, slippage=record.slippage,
            timestamp=aware(record.timestamp), reason=record.reason,
        )

    def positions(self) -> list[Position]:
        with self.db.session() as session:
            return [self.to_position(row) for row in session.scalars(select(PositionRecord).order_by(PositionRecord.opened_at)).all()]

    def orders(self, limit: int = 200) -> list[Order]:
        with self.db.session() as session:
            rows = session.scalars(select(OrderRecord).order_by(OrderRecord.created_at.desc()).limit(limit)).all()
            return [self.to_order(row) for row in rows]

    def fills(self, limit: int = 500) -> list[Fill]:
        with self.db.session() as session:
            rows = session.scalars(select(FillRecord).order_by(FillRecord.timestamp.desc()).limit(limit)).all()
            return [self.to_fill(row) for row in rows]

    def snapshot(self, *, now: datetime | None = None) -> PortfolioSnapshot:
        self.ensure_account()
        with self.db.session() as session:
            account = session.get(AccountRecord, 1)
            records = session.scalars(select(PositionRecord)).all()
            positions = [self.to_position(row) for row in records]
            current = now or datetime.now(timezone.utc)
            if account.last_reset_date != current.date().isoformat():
                account.day_start_equity = account.equity
                account.last_reset_date = current.date().isoformat()
            unrealized = sum(position.unrealized_pnl() for position in positions)
            equity = account.cash + sum(
                position.quantity * position.mark_price * (1 if position.side.value == "LONG" else -1)
                for position in positions
            )
            account.equity = equity
            account.high_water_mark = max(account.high_water_mark, equity)
            drawdown = max(0.0, (account.high_water_mark - equity) / account.high_water_mark) if account.high_water_mark else 0.0
            gross = sum(position.quantity * position.mark_price for position in positions) / equity if equity > 0 else 0.0
            portfolio_risk = sum(abs(position.entry_price - position.stop_loss) * position.quantity for position in positions) / equity if equity > 0 else 0.0
            daily_pnl = equity - account.day_start_equity
            reasons = list(account.halt_reasons or [])
            if daily_pnl <= -self.risk.max_daily_loss_pct * account.day_start_equity and "DAILY_LOSS_LIMIT" not in reasons:
                reasons.append("DAILY_LOSS_LIMIT")
            if drawdown >= self.risk.max_account_drawdown_pct and "MAX_DRAWDOWN_LIMIT" not in reasons:
                reasons.append("MAX_DRAWDOWN_LIMIT")
            account.trading_halted = bool(reasons)
            account.halt_reasons = reasons
            session.add(EquityRecord(equity=equity, cash=account.cash, daily_pnl=daily_pnl, drawdown_pct=drawdown))
            return PortfolioSnapshot(
                equity=equity, cash=account.cash, buying_power=max(0.0, account.cash), initial_equity=account.initial_equity,
                day_start_equity=account.day_start_equity, realized_pnl=account.realized_pnl, daily_pnl=daily_pnl,
                unrealized_pnl=unrealized, high_water_mark=account.high_water_mark, drawdown_pct=drawdown,
                gross_exposure_pct=gross, portfolio_risk_pct=portfolio_risk, open_positions=positions,
                trading_halted=bool(reasons), halt_reasons=reasons, as_of=current,
            )

    def save_run(self, request: ResearchRequest, report: FinalReport) -> None:
        payload = report.model_dump(mode="json")
        with self.db.session() as session:
            session.add(RunRecord(run_id=report.run_id, ticker=request.ticker, timeframe=request.timeframe, request=request.request, outcome=report.outcome.value, report=payload))
            # Flush first: agent_traces references research_runs via a foreign
            # key. SQLAlchemy's unit of work does not guarantee the parent row
            # is inserted before the child in this configuration, so insert
            # research_runs explicitly or the FK constraint rejects the traces.
            session.flush()
            for trace in report.traces:
                session.add(AgentTraceRecord(run_id=report.run_id, agent=trace.agent, status=trace.status.value, duration_ms=trace.duration_ms, trace=trace.model_dump(mode="json")))
            session.add(JournalRecord(run_id=report.run_id, event_type="FINAL_REPORT", payload={"outcome": report.outcome.value, "reasons": report.reasons}))

    def runs(self, limit: int = 50) -> list[dict]:
        with self.db.session() as session:
            rows = session.scalars(select(RunRecord).order_by(RunRecord.created_at.desc()).limit(limit)).all()
            return [{"run_id": row.run_id, "ticker": row.ticker, "timeframe": row.timeframe, "request": row.request, "outcome": row.outcome, "created_at": aware(row.created_at).isoformat()} for row in rows]

    def get_run(self, run_id: str) -> dict | None:
        with self.db.session() as session:
            row = session.get(RunRecord, run_id)
            return row.report if row else None

    def traces(self, run_id: str | None = None, limit: int = 500) -> list[dict]:
        with self.db.session() as session:
            query = select(AgentTraceRecord).order_by(AgentTraceRecord.id.desc()).limit(limit)
            if run_id:
                query = query.where(AgentTraceRecord.run_id == run_id)
            return [row.trace for row in session.scalars(query).all()]

    def journal(self, limit: int = 200) -> list[dict]:
        with self.db.session() as session:
            rows = session.scalars(select(JournalRecord).order_by(JournalRecord.id.desc()).limit(limit)).all()
            return [{"run_id": row.run_id, "event_type": row.event_type, "payload": row.payload, "created_at": aware(row.created_at).isoformat()} for row in rows]

    def log(self, event_type: str, payload: dict, run_id: str | None = None) -> None:
        with self.db.session() as session:
            session.add(JournalRecord(run_id=run_id, event_type=event_type, payload=payload))

    def equity_history(self, limit: int = 1000) -> list[dict]:
        with self.db.session() as session:
            rows = session.scalars(select(EquityRecord).order_by(EquityRecord.id.desc()).limit(limit)).all()
            return [{"timestamp": aware(row.timestamp).isoformat(), "equity": row.equity, "cash": row.cash, "daily_pnl": row.daily_pnl, "drawdown_pct": row.drawdown_pct} for row in reversed(rows)]

    def reset(self) -> None:
        with self.db.session() as session:
            for model in (PositionRecord, OrderRecord, FillRecord, EquityRecord, JournalRecord):
                session.query(model).delete()
            account = session.get(AccountRecord, 1)
            if account:
                session.delete(account)
        self.ensure_account()
