"""Mock broker adapter: a realistic sample portfolio across three accounts.

Demonstrates the value proposition — heavy tech overlap between direct holdings
and multiple S&P 500 / Nasdaq ETFs, so the look-through engine surfaces a large
*true* NVIDIA / AAPL exposure the user wouldn't see from account balances alone.
"""
from __future__ import annotations

from app.models import AccountType, Holding
from app.providers.base import BrokerAdapter


class MockBroker(BrokerAdapter):
    def get_holdings(self) -> list[Holding]:
        return [
            # Taxable brokerage — direct tech + broad-market ETFs
            Holding(ticker="NVDA", shares=40, account_type=AccountType.brokerage, cost_basis=6000),
            Holding(ticker="AAPL", shares=50, account_type=AccountType.brokerage, cost_basis=8000),
            Holding(ticker="SPY", shares=30, account_type=AccountType.brokerage, cost_basis=15000),
            Holding(ticker="QQQ", shares=25, account_type=AccountType.brokerage, cost_basis=10000),

            # Roth IRA — growth + international
            Holding(ticker="VTI", shares=40, account_type=AccountType.roth, cost_basis=9000),
            Holding(ticker="VXUS", shares=60, account_type=AccountType.roth, cost_basis=3500),
            Holding(ticker="TSLA", shares=20, account_type=AccountType.roth, cost_basis=5000),

            # 401k — dividend + S&P
            Holding(ticker="VOO", shares=35, account_type=AccountType._401k, cost_basis=14000),
            Holding(ticker="SCHD", shares=200, account_type=AccountType._401k, cost_basis=15000),
        ]
