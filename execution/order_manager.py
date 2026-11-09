"""Translation from approved proposals to paper-broker orders."""
from __future__ import annotations

from execution.paper_broker import PaperBroker
from models.trade import ExecutionResult, Order, OrderType, TradeProposal


class OrderManager:
    def __init__(self, broker: PaperBroker):
        self.broker = broker

    def execute(self, proposal: TradeProposal) -> ExecutionResult:
        order = Order(
            client_order_id=proposal.client_order_id,
            run_id=proposal.run_id,
            symbol=proposal.symbol,
            side=proposal.side,
            order_type=proposal.order_type,
            quantity=proposal.quantity,
            limit_price=proposal.entry_price if proposal.order_type == OrderType.LIMIT else None,
            stop_loss=proposal.stop_loss,
            take_profit=proposal.take_profit,
        )
        return self.broker.submit_order(order, market_price=proposal.entry_price)
