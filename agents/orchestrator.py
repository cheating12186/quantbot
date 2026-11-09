"""Composition root and public orchestrator for UI, API, and tests."""
from __future__ import annotations

from pydantic import BaseModel, Field

from agents.llm import GroqService
from agents.market_analyst import MarketAnalyst
from agents.money_manager import MoneyManager
from agents.news_analyst import NewsSentimentAnalyst
from agents.portfolio_monitor import PortfolioMonitor
from agents.risk_manager import RiskManager
from agents.rules_auditor import StrategyRulesAuditor
from agents.trade_supervisor import TradeSupervisor
from config.settings import Settings, get_risk_config, get_settings, get_strategy_config
from database.db import Database
from database.repository import Repository
from execution.order_manager import OrderManager
from execution.paper_broker import PaperBroker
from execution.safety_engine import DeterministicSafetyEngine
from models.agent_outputs import FinalReport
from models.trade import ResearchRequest
from orchestration.workflow import TradingWorkflow
from tools.market_data import MarketDataService, SyntheticMarketDataProvider, YFinanceProvider
from tools.news import build_news_provider
from tools.oanda import OandaMarketDataProvider


class ResearchIntent(BaseModel):
    objective: str = Field(min_length=3, max_length=1000)
    ticker: str
    timeframe: str = Field(pattern="^(5m|15m|1h|1d)$")


class QuantPilotOrchestrator:
    """Coordinates validated inputs and delegates all decisions to the workflow.

    This class has no database-write methods and cannot override a risk veto.
    """
    def __init__(self, settings: Settings | None = None, database: Database | None = None, market_data: MarketDataService | None = None):
        self.settings = settings or get_settings()
        self.risk_config = get_risk_config()
        self.strategy_config = get_strategy_config()
        self.database = database or Database(self.settings.database_url)
        self.repository = Repository(self.database, self.risk_config)
        self.broker = PaperBroker(self.database, self.repository, self.risk_config)
        if market_data is None:
            synthetic = SyntheticMarketDataProvider()
            oanda = None
            if self.settings.oanda_api_key and self.settings.oanda_account_id:
                oanda = OandaMarketDataProvider(
                    self.settings.oanda_api_key,
                    self.settings.oanda_account_id,
                    self.settings.oanda_environment,
                )
            if self.settings.data_provider == "synthetic":
                service = MarketDataService(provider=synthetic, max_data_age=self.risk_config.max_data_age_minutes)
            elif self.settings.data_provider == "oanda":
                if oanda is None:
                    raise RuntimeError("DATA_PROVIDER=oanda requires OANDA_API_KEY and OANDA_ACCOUNT_ID")
                # Strict mode: never disguise a provider outage with synthetic forex data.
                service = MarketDataService(provider=oanda, max_data_age=self.risk_config.max_data_age_minutes)
            elif self.settings.data_provider == "yfinance":
                service = MarketDataService(provider=YFinanceProvider(), max_data_age=self.risk_config.max_data_age_minutes)
            else:
                service = MarketDataService(
                    provider=oanda or YFinanceProvider(),
                    fallback=synthetic if self.settings.allow_synthetic_fallback else None,
                    max_data_age=self.risk_config.max_data_age_minutes,
                )
            market_data = service
        self.market_data = market_data
        self.llm = GroqService(self.settings)
        self.portfolio_monitor = PortfolioMonitor(self.repository, self.broker)
        self.workflow = TradingWorkflow(
            market_data=market_data,
            market_analyst=MarketAnalyst(self.strategy_config),
            news_analyst=NewsSentimentAnalyst(build_news_provider(
                self.settings.news_provider,
                finnhub_api_key=self.settings.finnhub_api_key,
                news_api_key=self.settings.news_api_key,
                cache_ttl_seconds=self.settings.news_cache_ttl_seconds,
            )),
            rules_auditor=StrategyRulesAuditor(self.strategy_config),
            risk_manager=RiskManager(self.risk_config),
            money_manager=MoneyManager(self.risk_config),
            supervisor=TradeSupervisor(self.llm),
            portfolio_monitor=self.portfolio_monitor,
            safety_engine=DeterministicSafetyEngine(self.repository, self.risk_config),
            order_manager=OrderManager(self.broker),
            repository=self.repository,
            strategy=self.strategy_config,
        )

    def run(self, request: ResearchRequest) -> FinalReport:
        return self.workflow.run(request)

    def parse_natural_language(self, text: str, default_ticker: str = "AAPL", default_timeframe: str = "1d") -> ResearchRequest:
        """Optional structured Groq tool call with deterministic fallback parsing."""
        fallback = ResearchRequest(ticker=default_ticker, timeframe=default_timeframe, request=text)
        if not self.llm.available:
            return fallback
        result = self.llm.tool_call(
            "set_research_parameters",
            ResearchIntent,
            "Extract trading research parameters. Never invent prices or performance. Use the supplied defaults when ambiguous.",
            f"Defaults: ticker={default_ticker}, timeframe={default_timeframe}. User request: {text}",
        )
        if not result.value:
            return fallback
        try:
            return ResearchRequest(ticker=result.value.ticker, timeframe=result.value.timeframe, request=result.value.objective)
        except Exception:
            return fallback
