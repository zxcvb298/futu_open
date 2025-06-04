from futu import *
from futu.common.constant import RET_OK
import logging
import time
from .utils import VIRTUAL_ORDERS, PENDING_ORDERS, CLOSING_ORDERS
from .close_order import CloseOrder

class MonitorStopLossTakeProfit:
    def __init__(self, quote_ctx, trd_ctx, trd_env):
        self.quote_ctx = quote_ctx
        self.trd_ctx = trd_ctx
        self.trd_env = trd_env
        self.close_order = CloseOrder(quote_ctx, trd_ctx, trd_env)

    def get_market_price(self, code):
        """獲取合約最新市場價格"""
        try:
            ret, data = self.quote_ctx.get_market_snapshot([code])
            if ret == RET_OK and not data.empty:
                price = data['last_price'][0]
                logging.debug(f"獲取 {code} 市場價格：{price}")
                return price
            else:
                logging.error(f"無法獲取 {code} 價格：{data}")
                return None
        except Exception as e:
            logging.error(f"獲取 {code} 價格異常：{e}")
            return None

    def monitor(self):
        """監控所有已成交持倉的止盈止損條件，每 2 秒檢查一次"""
        while True:
            try:
                # 在 for 迴圈外獲取價格
                current_price = None
                for order in VIRTUAL_ORDERS[:]:
                    code = order['code']
                    # 僅在第一次迭代或不同合約時獲取價格
                    if current_price is None or order['code'] != code:
                        current_price = self.get_market_price(code)
                        if current_price is None:
                            continue

                    if not order['is_open'] or order['quantity'] <= 0 or order['id'] in CLOSING_ORDERS or order.get('is_closing', False):
                        continue

                    direction = order['direction']
                    trigger_reason = None

                    # 更新價格極值
                    if direction == 'long':
                        order['highest_price'] = max(order.get('highest_price', current_price), current_price)
                    else:
                        order['lowest_price'] = min(order.get('lowest_price', current_price), current_price)

                    # 檢查移動止盈（Trailing Take Profit）
                    use_trailing = order.get('use_trailing', False)
                    if use_trailing:
                        if direction == 'long':
                            # 多單：價格從最高點回撤超過 100 點
                            if current_price <= order['highest_price'] - 100:
                                trigger_reason = f"移動止盈觸發（當前價格 {current_price} <= 最高價 {order['highest_price']} - 100）"
                        else:
                            # 空單：價格從最低點反彈超過 100 點
                            if current_price >= order['lowest_price'] + 100:
                                trigger_reason = f"移動止盈觸發（當前價格 {current_price} >= 最低價 {order['lowest_price']} + 100）"

                    # 檢查固定止盈止損
                    if not trigger_reason:
                        stop_loss = order.get('stop_loss')
                        take_profit = order.get('take_profit')
                        if stop_loss is None and take_profit is None:
                            continue  # 無止盈止損設定，跳過

                        if direction == 'long':
                            if stop_loss is not None and current_price <= stop_loss:
                                trigger_reason = f"止損觸發（當前價格 {current_price} <= 止損價格 {stop_loss}）"
                            elif take_profit is not None and current_price >= take_profit:
                                trigger_reason = f"止盈觸發（當前價格 {current_price} >= 止盈價格 {take_profit}）"
                        elif direction == 'short':
                            if stop_loss is not None and current_price >= stop_loss:
                                trigger_reason = f"止損觸發（當前價格 {current_price} >= 止損價格 {stop_loss}）"
                            elif take_profit is not None and current_price <= take_profit:
                                trigger_reason = f"止盈觸發（當前價格 {current_price} <= 止盈價格 {take_profit}）"

                    if trigger_reason:
                        logging.info(f"訂單 {order['id']} 觸發自動平倉：{trigger_reason}")
                        order['is_closing'] = True  # 標記為正在平倉
                        CLOSING_ORDERS.add(order['id'])
                        success, _, _, _, msg = self.close_order.execute(
                            order_id=order['id'],
                            qty=order['quantity'],
                            direction=order['direction'],
                            price=None
                        )
                        if success:
                            logging.info(f"自動平倉提交成功：{msg}")
                        else:
                            logging.error(f"自動平倉失敗：{msg}")
                            CLOSING_ORDERS.remove(order['id'])
                            order['is_closing'] = False  # 平倉失敗，重置標記
                        # time.sleep(0.5)

                time.sleep(1)  # 每 2 秒檢查一次
            except Exception as e:
                logging.error(f"止盈止損監控異常：{e}")
                time.sleep(5)