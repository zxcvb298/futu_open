from futu import *
from futu.common.constant import RET_OK
import logging
from .utils import PENDING_ORDERS

class OpenOrder:
    def __init__(self, quote_ctx, trd_ctx, trd_env, order_counter):
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

    def execute(self, code, direction, qty, price=None):
        """提交開倉訂單"""
        try:
            if price is None:
                price = self.get_market_price(code)
                if price is None:
                    error_msg = "無法獲取市場價格"
                    logging.error(error_msg)
                    return False, error_msg

            custom_order_id = f"HSI-{self.order_counter:03d}"  # 生成 ID 前不增量
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
                    'order_type': 'open'
                }
                self.order_counter += 1  # 提交成功後增量
                success_msg = f"開倉訂單提交成功：訂單ID={custom_order_id}"
                logging.info(f"開倉訂單提交：訂單ID={custom_order_id}, 合約={code}, 方向={direction}, 數量={qty}, 開倉價格={price}")
                return True, success_msg
            else:
                error_msg = f"開倉訂單提交失敗：{data}"
                logging.error(error_msg)
                return False, error_msg
        except Exception as e:
            error_msg = f"開倉訂單提交異常：{e}"
            logging.error(error_msg)
            return False, error_msg