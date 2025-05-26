from futu import *
from futu.common.constant import RET_OK  # 明確匯入 RET_OK
import logging
from .utils import VIRTUAL_ORDERS, PENDING_ORDERS

class CloseOrder:
    def __init__(self, quote_ctx, trd_ctx, trd_env):
        self.quote_ctx = quote_ctx
        self.trd_ctx = trd_ctx
        self.trd_env = trd_env

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

    def execute(self, order_id, qty, direction, price=None):
        """提交平倉訂單，根據訂單 ID 平倉"""
        try:
            virtual_order = next((order for order in VIRTUAL_ORDERS if order['id'] == order_id and order['direction'] == direction.lower() and order['is_open']), None)
            if not virtual_order:
                error_msg = f"未找到訂單ID為 {order_id} 方向為 {direction} 的開倉訂單"
                logging.error(error_msg)
                return False, 0, 0, 0, error_msg

            if virtual_order['quantity'] < qty:
                error_msg = f"訂單 {order_id} 數量不足：可用 {virtual_order['quantity']}, 要求 {qty}"
                logging.error(error_msg)
                return False, 0, 0, 0, error_msg

            code = virtual_order['code']
            if price is None:
                price = self.get_market_price(code)
                if price is None:
                    error_msg = "無法獲取市場價格"
                    logging.error(error_msg)
                    return False, 0, 0, 0, error_msg

            custom_order_id = order_id
            trd_side = TrdSide.SELL if direction.lower() == 'long' else TrdSide.BUY
            entry_price = virtual_order['entry_price']

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
                    'entry_price': entry_price,
                    'order_type': 'close'
                }
                success_msg = f"平倉訂單提交成功：訂單ID={custom_order_id}"
                logging.info(f"平倉訂單提交：訂單ID={custom_order_id}, 合約={code}, 方向={direction}, 數量={qty}, 平倉價格={price}")
                return True, 0, 0, 0, success_msg
            else:
                error_msg = f"平倉訂單提交失敗：{data}"
                logging.error(error_msg)
                return False, 0, 0, 0, error_msg
        except Exception as e:
            error_msg = f"平倉訂單提交異常：{e}"
            logging.error(error_msg)
            return False, 0, 0, 0, error_msg