"""QuantConnect Research 20886 faithful implementation; run inside LEAN/QC only."""

import numpy as np
from AlgorithmImports import *


class SelectionData:
    def __init__(self, period, top_returns):
        self.volume = SimpleMovingAverage(period)
        self.returns = RateOfChange(1)
        self.returns.window.size = period
        self.top_returns = top_returns

    def update(self, fundamental):
        self.volume.update(fundamental.end_time, fundamental.dollar_volume)
        self.returns.update(fundamental.end_time, fundamental.adjusted_price)
        return self.volume.is_ready and self.returns.is_ready

    @property
    def factor(self):
        return float(np.mean(sorted(x.value for x in self.returns.window)[-self.top_returns:]))


class MaxEffectVixAlgorithm(QCAlgorithm):
    """Bottom MAX decile, cap 25, with the published VIX leverage rule."""
    def initialize(self):
        self.set_start_date(1998, 1, 1)
        self.set_cash(1_000_000)
        self.period, self.top_returns = 21, 5
        self.max_positions, self.min_dollar_volume = 25, 5_000_000
        self.low_vix, self.high_vix = 15, 30
        self._data = {}
        self._universe = self.add_universe(self._select_assets)
        self._vix = self.add_data(CBOE, "VIX", Resolution.DAILY).symbol
        self.spy = self.add_equity("SPY", Resolution.DAILY).symbol
        self.schedule.on(self.date_rules.month_start(self.spy, 1), self.time_rules.at(8, 0), self._rebalance)

    def _select_assets(self, fundamentals):
        selected = []
        for f in fundamentals:
            if (f.company_reference.is_reit or f.security_reference.is_depositary_receipt
                    or not f.has_fundamental_data or f.price < 5 or f.market_cap < 1_000_000_000):
                continue
            data = self._data.setdefault(f.symbol, SelectionData(self.period, self.top_returns))
            if data.update(f):
                selected.append(f.symbol)
        return selected

    def _leverage(self):
        vix = self.securities[self._vix].price
        if not vix or vix >= self.high_vix:
            return 1.0
        if vix <= self.low_vix:
            return 1.5
        return 1.5 - (vix - self.low_vix) / self.low_vix * 0.5

    def _rebalance(self):
        factors = {}
        for symbol in self._universe.selected:
            security = self.securities[symbol]
            data = self._data.get(symbol)
            if security.price and data and data.volume.current.value >= self.min_dollar_volume:
                factors[symbol] = data.factor
        count = min(self.max_positions, len(factors) // 10)
        chosen = [symbol for symbol, _ in sorted(factors.items(), key=lambda item: item[1])[:count]]
        if not chosen:
            return
        leverage = self._leverage()
        self.set_holdings([PortfolioTarget(symbol, leverage / len(chosen)) for symbol in chosen],
                          liquidate_existing_holdings=True)

    def on_data(self, data):
        # The original research also resizes when VIX moves across its thresholds.
        if self._vix not in data or not self.portfolio.invested:
            return
        leverage = self._leverage()
        invested = [x for x in self.portfolio.values() if x.invested and x.symbol != self.spy]
        if invested:
            self.set_holdings([PortfolioTarget(x.symbol, leverage / len(invested)) for x in invested])
