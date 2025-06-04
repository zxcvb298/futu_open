from futu import *
from futu.common.constant import RET_OK
import logging
from .utils import VIRTUAL_ORDERS, PENDING_ORDERS

class GetPositions:
    def __init__(self, quote_ctx):
        self.quote_ctx = quote_ctx

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

    def execute(self):
        """查詢並記錄當前虛擬訂單和待成交訂單"""
        try:
            has_positions = False

            if VIRTUAL_ORDERS:
                logging.info("=== 當前持倉 ===")
                for order in VIRTUAL_ORDERS:
                    if order['is_open'] and order['quantity'] > 0:
                        direction_text = '多' if order['direction'] == 'long' else '空'
                        current_price = self.get_market_price(order['code'])
                        if current_price is not None:
                            if order['direction'] == 'long':
                                pnl = (current_price - order['entry_price']) * order['quantity'] * 10
                            else:
                                pnl = (order['entry_price'] - current_price) * order['quantity'] * 10
                            pnl_text = f"{pnl:.2f}"
                        else:
                            pnl_text = "無法計算盈虧"
                        stop_loss = order.get('stop_loss', '無')
                        take_profit = order.get('take_profit', '無')
                        logging.info(f"ID: {order['id']}, 合約={order['code']}, 方向={direction_text}, "
                                     f"數量={order['quantity']}, 價格={order['entry_price']}, 止損={stop_loss}, 止盈={take_profit}, "
                                     f"浮動盈虧={pnl_text}")
                        has_positions = True

            if PENDING_ORDERS:
                logging.info("=== 待成交訂單 ===")
                for futu_order_id, order in PENDING_ORDERS.items():
                    direction_text = '多' if order['direction'] == 'long' else '空'
                    order_type_text = '開倉' if order['order_type'] == 'open' else '平倉'
                    stop_loss = order.get('stop_loss', '無')
                    take_profit = order.get('take_profit', '無')
                    logging.info(f"ID: {order['id']}, 合約={order['code']}, 方向={direction_text}, "
                                 f"數量={order['qty']}, 價格={order['price']}, 止損={stop_loss}, 止盈={take_profit}, "
                                 f"類型={order_type_text}")
                    has_positions = True

            if not has_positions:
                logging.info("查詢持倉：無持倉或待成交訂單")
                return False, "無持倉或待成交訂單"

            success_msg = "持倉查詢完成"
            return True, success_msg
        except Exception as e:
            error_msg = f"查詢持倉異常：{str(e)}"
            logging.error(error_msg)
            return False, error_msg