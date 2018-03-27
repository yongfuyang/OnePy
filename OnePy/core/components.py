from itertools import count

from OnePy.constants import OrderType
from OnePy.core.base_order import (LimitBuyOrder, LimitCoverShortOrder,
                                   LimitSellOrder, LimitShortSellOrder,
                                   MarketOrder, StopBuyOrder,
                                   StopCoverShortOrder, StopSellOrder,
                                   StopShortSellOrder, TrailingStopSellOrder,
                                   TrailingStopShortSellOrder)
from OnePy.model.signals import Signal


class MarketMaker(object):

    env = None
    gvar = None

    def __init__(self):

        self.data_Buffer = None
        self.ohlc = None
        self.tick_data = None
        self.execute_price = None

    def update_market(self):
        try:
            for iter_bar in self.env.feeds.values():
                iter_bar.next()

            return True
        except StopIteration:
            return False


class SignalGenerator(object):

    """存储Signal的信息"""
    env = None
    gvar = None

    def __init__(self, order_type):
        self.order_type = order_type

    def func_1(self, units, ticker,
               takeprofit=None, takeprofit_pct=None,
               stoploss=None, stoploss_pct=None,
               trailingstop=None, trailingstop_pct=None,
               price=None, price_pct=None):

        return Signal(
            order_type=self.order_type,
            units=units,
            ticker=ticker,
            datetime=self.env.feeds[ticker].date,
            takeprofit=takeprofit,
            takeprofit_pct=takeprofit_pct,
            stoploss=stoploss,
            stoploss_pct=stoploss_pct,
            trailingstop=trailingstop,
            trailingstop_pct=trailingstop_pct,
            price=price,
            price_pct=price_pct,
        )

    def func_2(self, units, ticker, price=None, price_pct=None):

        return Signal(
            order_type=self.order_type,
            units=units,
            ticker=ticker,
            datetime=self.env.feeds[ticker].date,
            price=price,
            price_pct=price_pct,
        )


class OrderGenerator(object):

    env = None
    gvar = None
    counter = count(1)

    def __init__(self, signal):
        self.signal = signal
        self.mkt_id = next(self.counter)

        self.market_order = None
        self.orders_pending_mkt = []
        self.orders_pending = []

    @property
    def cur_price(self):
        return self.env.feeds[self.signal.ticker].cur_price

    def is_buy(self):
        return True if self.signal.order_type == OrderType.BUY else False

    def is_sell(self):
        return True if self.signal.order_type == OrderType.SELL else False

    def is_shortsell(self):
        return True if self.signal.order_type == OrderType.SHORT_SELL else False

    def is_shortcover(self):
        return True if self.signal.order_type == OrderType.SHORT_COVER else False

    def is_exitall(self):
        return True if self.signal.order_type == OrderType.EXIT_ALL else False

    def is_cancelall(self):
        return True if self.signal.order_type == OrderType.CANCEL_ALL else False

    def is_absolute_mkt(self):
        return True if self.signal.execute_price else False

    def is_normal_mkt(self):
        return False if self.signal.price or self.signal.price_pct else True

    def is_marketorder(self):
        if self.is_absolute_mkt() or self.is_normal_mkt():
            return True

        return False

    def set_market_order(self):
        self.market_order = MarketOrder(self.signal, self.mkt_id, None)

    def clarify_pct_except_price_pct(self):
        for key in ['takeprofit', 'stoploss', 'trailingstop']:
            pct = self.signal.get(f'{key}_pct')

            if pct:
                self.signal.set(key, abs(pct*self.cur_price*self.signal.units))

    def clarify_price_pct(self):
        if self.signal.price_pct:
            self.signal.price = (self.signal.price_pct+1)*self.cur_price

    def child_of_mkt(self, order_class, key):
        if self.signal.get(key):
            self.orders_pending_mkt.append(
                order_class(self.signal, self.mkt_id, key))

    def pending_order_only(self, order_class):
        self.orders_pending.append(order_class(self.signal, self.mkt_id, None))

    def _generate_child_order_of_mkt(self):
        self.clarify_pct_except_price_pct()

        if self.is_buy():
            self.child_of_mkt(StopSellOrder, 'stoploss')
            self.child_of_mkt(LimitSellOrder, 'takeprofit')
            self.child_of_mkt(TrailingStopSellOrder, 'trailingstop')

        elif self.is_shortsell():
            self.child_of_mkt(StopShortSellOrder, 'stoploss')
            self.child_of_mkt(LimitShortSellOrder, 'takeprofit')
            self.child_of_mkt(
                TrailingStopShortSellOrder, 'trailingstop')

    def _generate_pending_order_only(self):
        self.clarify_price_pct()

        if self.signal.price > self.cur_price:
            if self.is_buy():
                self.pending_order_only(StopBuyOrder)
            elif self.is_shortcover():
                self.pending_order_only(StopCoverShortOrder)
            elif self.is_sell():
                self.pending_order_only(LimitSellOrder)
            elif self.is_shortsell():
                self.pending_order_only(LimitCoverShortOrder)
        elif self.signal.price < self.cur_price:
            if self.is_buy():
                self.pending_order_only(LimitBuyOrder)
            elif self.is_shortcover():
                self.pending_order_only(LimitBuyOrder)
            elif self.is_sell():
                self.pending_order_only(StopSellOrder)
            elif self.is_shortsell():
                self.pending_order_only(StopShortSellOrder)
        else:
            self.signal.execute_price = self.cur_price
            self.generate_order()

    def generate_order(self):

        if self.is_exitall():
            pass  # TODO:写逻辑

        elif self.is_cancelall():
            pass  # TODO:写逻辑

        elif self.is_marketorder():
            self.set_market_order()
            self._generate_child_order_of_mkt()

        else:
            self._generate_pending_order_only()

    def submit_order_to_env(self):
        if self.market_order:
            self.env.orders_mkt_original.append(self.market_order)

            if self.is_absolute_mkt(self):
                self.env.orders_mkt_absolute.append(self.market_order)
            elif self.is_normal_mkt(self):
                self.env.orders_mkt_normal.append(self.market_order)

            if self.orders_pending_mkt != []:
                self.env.orders_pending_mkt_dict.update(
                    {self.mkt_id: self.orders_pending_mkt})
        else:
            self.env.orders_pending += self.orders_pending