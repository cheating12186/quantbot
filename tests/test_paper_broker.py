from datetime import datetime, timezone

import pytest

from config.settings import get_risk_config
from database.db import Database
from database.models import AccountRecord
from database.repository import Repository
from execution.paper_broker import DuplicateOrderError, PaperBroker
from models.trade import Order, OrderType, Side


@pytest.fixture
def broker(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'broker.db'}")
    repository = Repository(database, get_risk_config())
    return PaperBroker(database, repository, get_risk_config())


def order(client_id="unique", order_type=OrderType.MARKET, **kwargs):
    values = dict(client_order_id=client_id, symbol="TEST", side=Side.LONG, order_type=order_type, quantity=10, stop_loss=95, take_profit=110, limit_price=99 if order_type == OrderType.LIMIT else None)
    values.update(kwargs)
    return Order(**values)


def test_duplicate_orders_are_prevented(broker):
    broker.submit_order(order(), market_price=100)
    with pytest.raises(DuplicateOrderError):
        broker.submit_order(order(), market_price=100)


def test_paper_trade_accounting_and_partial_close(broker):
    result = broker.submit_order(order(), market_price=100)
    assert result.executed
    assert result.fill.price == pytest.approx(100.02)
    snapshot = broker.repository.snapshot()
    assert snapshot.cash == pytest.approx(100000 - 1000.2 - 0.10002)
    first = broker.close_position("TEST", 4, 101)
    assert first.quantity == 4
    positions = broker.repository.positions()
    assert positions[0].quantity == pytest.approx(6)
    second = broker.close_position("TEST", 6, 101)
    assert broker.repository.positions() == []
    final = broker.repository.snapshot()
    assert final.realized_pnl > 0
    # With no open position, all entry/exit fees must be reflected in realized P&L.
    assert final.realized_pnl == pytest.approx(final.equity - final.initial_equity)
    assert first.fill_id != second.fill_id


def test_short_accounting(broker):
    broker.submit_order(order(side=Side.SHORT, stop_loss=105, take_profit=90), market_price=100)
    snapshot = broker.repository.snapshot()
    assert snapshot.cash > 100000  # Short sale proceeds less fees.
    broker.close_position("TEST", 10, 95)
    assert broker.repository.snapshot().realized_pnl > 0


def test_limit_order_cancellation_and_fill(broker):
    pending = broker.submit_order(order("limit", OrderType.LIMIT), market_price=100)
    assert not pending.executed
    cancelled = broker.cancel_order(pending.order.order_id)
    assert cancelled.status.value == "CANCELLED"
    other = broker.submit_order(order("limit2", OrderType.LIMIT), market_price=100)
    fills = broker.process_candle("TEST", 100, 101, 98, 99.5)
    assert any(fill.reason == "ENTRY" for fill in fills)
    assert other.order.order_id in [fill.order_id for fill in fills]


def test_stop_loss_is_conservative_when_stop_and_target_share_candle(broker):
    broker.submit_order(order(), market_price=100)
    fills = broker.process_candle("TEST", 100, 111, 94, 100)
    assert len(fills) == 1
    assert fills[0].reason == "STOP_LOSS"
    assert broker.repository.snapshot().realized_pnl < 0


def test_daily_loss_and_drawdown_trigger_persistent_halt(broker):
    with broker.db.session() as session:
        account = session.get(AccountRecord, 1)
        account.cash = 97000
        account.equity = 97000
        account.high_water_mark = 100000
    snapshot = broker.repository.snapshot()
    assert snapshot.trading_halted
    assert "DAILY_LOSS_LIMIT" in snapshot.halt_reasons
    with broker.db.session() as session:
        account = session.get(AccountRecord, 1)
        account.cash = 94000
        account.equity = 94000
    snapshot = broker.repository.snapshot()
    assert "MAX_DRAWDOWN_LIMIT" in snapshot.halt_reasons
