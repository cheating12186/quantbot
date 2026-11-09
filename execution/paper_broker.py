"""SQLite-backed paper broker. No real-money adapter exists by design."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from config.settings import RiskConfig
from database.db import Database
from database.models import AccountRecord, FillRecord, JournalRecord, OrderRecord, PositionRecord
from database.repository import Repository, aware
from models.trade import ExecutionResult, Fill, Order, OrderStatus, OrderType, Side


class BrokerError(RuntimeError):
    pass


class DuplicateOrderError(BrokerError):
    pass


class PaperBroker:
    def __init__(self, database: Database, repository: Repository, risk: RiskConfig):
        self.db = database
        self.repository = repository
        self.risk = risk
        self.repository.ensure_account()

    @staticmethod
    def _order_record(order: Order) -> OrderRecord:
        return OrderRecord(
            order_id=order.order_id, client_order_id=order.client_order_id, run_id=order.run_id, symbol=order.symbol,
            side=order.side.value, order_type=order.order_type.value, quantity=order.quantity, limit_price=order.limit_price,
            stop_loss=order.stop_loss, take_profit=order.take_profit, status=OrderStatus.PENDING.value,
            created_at=order.created_at, updated_at=order.updated_at,
        )

    def submit_order(self, order: Order, market_price: float | None = None) -> ExecutionResult:
        if order.quantity <= 0:
            raise BrokerError("Order quantity must be positive")
        if order.order_type == OrderType.MARKET and (market_price is None or market_price <= 0):
            raise BrokerError("A positive market price is required for a market order")
        if order.order_type == OrderType.LIMIT and not order.limit_price:
            raise BrokerError("Limit price is required")
        with self.db.session() as session:
            duplicate = session.scalar(select(OrderRecord).where(OrderRecord.client_order_id == order.client_order_id))
            if duplicate:
                raise DuplicateOrderError(f"Duplicate client_order_id: {order.client_order_id}")
            record = self._order_record(order)
            session.add(record)
            session.flush()
            fill = None
            marketable_limit = False
            if order.order_type == OrderType.LIMIT and market_price is not None:
                marketable_limit = ((order.side == Side.LONG and market_price <= order.limit_price) or (order.side == Side.SHORT and market_price >= order.limit_price))
            if order.order_type == OrderType.MARKET or marketable_limit:
                reference = market_price if order.order_type == OrderType.MARKET else order.limit_price
                fill = self._fill_entry(session, record, float(reference))
            session.add(JournalRecord(run_id=order.run_id, event_type="ORDER_SUBMITTED", payload={"order_id": order.order_id, "status": record.status, "paper": True}))
            result_order = Repository.to_order(record)
        return ExecutionResult(executed=fill is not None, message="Paper order filled" if fill else "Paper limit order accepted", order=result_order, fill=fill)

    def _fill_entry(self, session, order: OrderRecord, reference_price: float) -> Fill:
        if reference_price <= 0:
            raise BrokerError("Fill price must be positive")
        account = session.get(AccountRecord, 1)
        existing = session.scalar(select(PositionRecord).where(PositionRecord.symbol == order.symbol))
        if existing:
            order.status = OrderStatus.REJECTED.value
            order.rejection_reason = "An open position already exists for this symbol"
            raise BrokerError(order.rejection_reason)
        sign = 1 if order.side == Side.LONG.value else -1
        slippage_rate = self.risk.slippage_bps / 10_000
        raw_price = reference_price * (1 + sign * slippage_rate)
        if order.order_type == OrderType.LIMIT.value:
            price = min(raw_price, order.limit_price) if sign == 1 else max(raw_price, order.limit_price)
        else:
            price = raw_price
        notional = price * order.quantity
        fees = notional * self.risk.fee_bps / 10_000
        # 100% margin assumption for paper shorts, full cash funding for longs.
        if account.cash + 1e-8 < notional + fees:
            order.status = OrderStatus.REJECTED.value
            order.rejection_reason = "Insufficient buying power at simulated fill"
            raise BrokerError(order.rejection_reason)
        account.cash += -sign * notional - fees
        timestamp = datetime.now(timezone.utc)
        position = PositionRecord(
            position_id=str(uuid.uuid4()), symbol=order.symbol, side=order.side, quantity=order.quantity,
            entry_price=price, stop_loss=order.stop_loss, take_profit=order.take_profit,
            opened_at=timestamp, mark_price=price, entry_fees=fees,
        )
        session.add(position)
        order.status = OrderStatus.FILLED.value
        order.filled_quantity = order.quantity
        order.average_fill_price = price
        order.fees = fees
        order.updated_at = timestamp
        fill_record = FillRecord(
            fill_id=str(uuid.uuid4()), order_id=order.order_id, symbol=order.symbol, side=order.side,
            quantity=order.quantity, price=price, fees=fees, slippage=abs(price - reference_price) * order.quantity,
            timestamp=timestamp, reason="ENTRY",
        )
        session.add(fill_record)
        session.add(JournalRecord(run_id=order.run_id, event_type="PAPER_FILL", payload=Repository.to_fill(fill_record).model_dump(mode="json")))
        return Repository.to_fill(fill_record)

    def cancel_order(self, order_id: str) -> Order:
        with self.db.session() as session:
            order = session.get(OrderRecord, order_id)
            if order is None:
                raise BrokerError("Order not found")
            if order.status != OrderStatus.PENDING.value:
                raise BrokerError("Only pending orders can be cancelled")
            order.status = OrderStatus.CANCELLED.value
            order.updated_at = datetime.now(timezone.utc)
            return Repository.to_order(order)

    def close_position(self, symbol: str, quantity: float, market_price: float, reason: str = "MANUAL_CLOSE") -> Fill:
        if quantity <= 0 or market_price <= 0:
            raise BrokerError("Close quantity and price must be positive")
        with self.db.session() as session:
            position = session.scalar(select(PositionRecord).where(PositionRecord.symbol == symbol))
            if position is None:
                raise BrokerError(f"No open position for {symbol}")
            quantity = min(quantity, position.quantity)
            account = session.get(AccountRecord, 1)
            sign = 1 if position.side == Side.LONG.value else -1
            # Longs sell into a slightly lower bid; shorts buy back at a higher ask.
            exit_price = market_price * (1 - sign * self.risk.slippage_bps / 10_000)
            fees = exit_price * quantity * self.risk.fee_bps / 10_000
            allocated_entry_fee = position.entry_fees * (quantity / position.quantity)
            realized = (exit_price - position.entry_price) * quantity * sign - fees - allocated_entry_fee
            account.cash += sign * exit_price * quantity - fees
            account.realized_pnl += realized
            position.realized_pnl += realized
            position.entry_fees = max(0.0, position.entry_fees - allocated_entry_fee)
            timestamp = datetime.now(timezone.utc)
            order = OrderRecord(
                order_id=str(uuid.uuid4()), client_order_id=f"close-{uuid.uuid4()}", symbol=symbol, side=position.side,
                order_type=OrderType.MARKET.value, quantity=quantity, stop_loss=position.stop_loss,
                take_profit=position.take_profit, status=OrderStatus.FILLED.value, filled_quantity=quantity,
                average_fill_price=exit_price, fees=fees, created_at=timestamp, updated_at=timestamp,
            )
            session.add(order)
            session.flush()
            fill = FillRecord(
                fill_id=str(uuid.uuid4()), order_id=order.order_id, symbol=symbol, side=position.side,
                quantity=quantity, price=exit_price, fees=fees,
                slippage=abs(exit_price - market_price) * quantity, timestamp=timestamp, reason=reason,
            )
            session.add(fill)
            position.quantity -= quantity
            if position.quantity <= 1e-8:
                session.delete(position)
            session.add(JournalRecord(event_type="POSITION_CLOSED", payload={"symbol": symbol, "quantity": quantity, "realized_pnl": realized, "reason": reason, "paper": True}))
            return Repository.to_fill(fill)

    def process_candle(self, symbol: str, open_: float, high: float, low: float, close: float) -> list[Fill]:
        """Fill limits and protective exits. If stop and target share a bar, stop wins."""
        if min(open_, high, low, close) <= 0 or high < low:
            raise BrokerError("Invalid candle")
        fills: list[Fill] = []
        with self.db.session() as session:
            pending = session.scalars(select(OrderRecord).where(OrderRecord.symbol == symbol, OrderRecord.status == OrderStatus.PENDING.value)).all()
            entries = []
            for order in pending:
                marketable = (order.side == Side.LONG.value and low <= order.limit_price) or (order.side == Side.SHORT.value and high >= order.limit_price)
                if marketable:
                    entries.append((order.order_id, order.limit_price))
        for order_id, limit_price in entries:
            with self.db.session() as session:
                order = session.get(OrderRecord, order_id)
                if order and order.status == OrderStatus.PENDING.value:
                    fills.append(self._fill_entry(session, order, limit_price))
        with self.db.session() as session:
            position = session.scalar(select(PositionRecord).where(PositionRecord.symbol == symbol))
            exit_spec = None
            if position:
                if position.side == Side.LONG.value:
                    if low <= position.stop_loss:
                        exit_spec = (position.quantity, position.stop_loss, "STOP_LOSS")
                    elif high >= position.take_profit:
                        exit_spec = (position.quantity, position.take_profit, "TAKE_PROFIT")
                else:
                    if high >= position.stop_loss:
                        exit_spec = (position.quantity, position.stop_loss, "STOP_LOSS")
                    elif low <= position.take_profit:
                        exit_spec = (position.quantity, position.take_profit, "TAKE_PROFIT")
        if exit_spec:
            fills.append(self.close_position(symbol, exit_spec[0], exit_spec[1], exit_spec[2]))
        self.mark_price(symbol, close)
        return fills

    def mark_price(self, symbol: str, price: float):
        if price <= 0:
            raise BrokerError("Mark price must be positive")
        with self.db.session() as session:
            position = session.scalar(select(PositionRecord).where(PositionRecord.symbol == symbol))
            if position:
                position.mark_price = price
        return self.repository.snapshot()
