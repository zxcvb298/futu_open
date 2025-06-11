from futu import *
from futu.common.constant import RET_OK
import logging
from .utils import load_config, PENDING_ORDERS

class OpenOrder:
    def __init__(self, quote_ctx, trd_ctx, trd_env, order_counter):
        config = load_config()
        self.FIXED_THRESHOLD = config['fixed_threshold']
        self.quote_ctx = quote_ctx
        self.trd_ctx = trd_ctx
        self.trd_env = trd_env
        self.order_counter = order_counter

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

    def validate_stop_loss_take_profit(self, direction, entry_price, stop_loss, take_profit):
        """驗證止盈止損價格是否符合條件"""
        if stop_loss is not None and take_profit is not None:
            direction = direction.lower()
            if direction == 'long':
                if stop_loss >= entry_price:
                    return False, f"止損價格 {stop_loss} 應低於開倉價格 {entry_price}（多頭）"
                if take_profit <= entry_price:
                    return False, f"止盈價格 {take_profit} 應高於開倉價格 {entry_price}（多頭）"
            elif direction == 'short':
                if stop_loss <= entry_price:
                    return False, f"止損價格 {stop_loss} 應高於開倉價格 {entry_price}（空頭）"
                if take_profit >= entry_price:
                    return False, f"止盈價格 {take_profit} 應低於開倉價格 {entry_price}（空頭）"
            else:
                return False, f"無效的方向：{direction}"
        return True, None

    def execute(self, code, direction, qty, price=None, stop_loss=None, take_profit=None, use_fix=False, use_trailing=False, point_id=None, hit_price=None):
        """提交開倉訂單，根據模式設置止盈止損"""
        try:
            if price == 'market': # 用市場價開單才成立
                price = self.get_market_price(code)
                if price is None:
                    error_msg = "無法獲取市場價格"
                    logging.error(error_msg)
                    return False, error_msg

            # 若使用 fix 或 trailing 模式，從 config 獲取固定止盈止損
            if use_fix or use_trailing:
                stop_loss = price - self.FIXED_THRESHOLD if direction.lower() == 'long' else price + self.FIXED_THRESHOLD
                take_profit = price + self.FIXED_THRESHOLD if direction.lower() == 'long' else price - self.FIXED_THRESHOLD

            # 驗證止盈止損價格
            if stop_loss is not None and take_profit is not None:
                valid, error_msg = self.validate_stop_loss_take_profit(direction, price, stop_loss, take_profit)
                if not valid:
                    logging.error(error_msg)
                    return False, error_msg

            custom_order_id = f"HSI-{self.order_counter:03d}"
            trd_side = TrdSide.BUY if direction.lower() == 'long' else TrdSide.SELL

            ret, data = self.trd_ctx.place_order(
                price=price,
                qty=qty,
                code=code,
                trd_side=trd_side,
                trd_env=self.trd_env,
                order_type=OrderType.NORMAL
            )
            if ret == RET_OK:
                futu_order_id = data['order_id'][0]
                PENDING_ORDERS[futu_order_id] = {
                    'id': custom_order_id,
                    'code': code,
                    'direction': direction.lower(),
                    'qty': qty,
                    'price': price,
                    'order_type': 'open',
                    'stop_loss': stop_loss,
                    'take_profit': take_profit,
                    'use_trailing': use_trailing,
                    'point_id': point_id,
                    'hit_price': hit_price
                }
                self.order_counter += 1
                success_msg = f"開倉訂單提交成功：訂單ID={custom_order_id}"
                logging.info(f"⭕ 開倉訂單提交：訂單ID={custom_order_id}, 合約={code}, 方向={direction}, 數量={qty}, 開倉價格={price}, 命中點位 ({[point_id]})={hit_price}")
                return True, success_msg
            else:
                error_msg = f"開倉訂單提交失敗：{data}"
                logging.error(error_msg)
                return False, error_msg
        except Exception as e:
            error_msg = f"開倉訂單提交異常：{e}"
            logging.error(error_msg)
            return False, error_msg