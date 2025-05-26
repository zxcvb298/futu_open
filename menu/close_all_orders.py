import logging
from .utils import VIRTUAL_ORDERS
from .close_order import CloseOrder

class CloseAllOrders:
    def __init__(self, quote_ctx, trd_ctx, trd_env):
        self.close_order = CloseOrder(quote_ctx, trd_ctx, trd_env)

    def execute(self):
        """平倉所有當前持倉的虛擬訂單"""
        try:
            if not any(order['is_open'] and order['quantity'] > 0 for order in VIRTUAL_ORDERS):
                logging.info("無持倉可平倉")
                return False, "無持倉可平倉"

            results = []
            for order in VIRTUAL_ORDERS:
                if order['is_open'] and order['quantity'] > 0:
                    success, _, _, _, msg = self.close_order.execute(
                        order_id=order['id'],
                        qty=order['quantity'],
                        direction=order['direction'],
                        price=None
                    )
                    results.append(msg)

            success = all("成功" in msg for msg in results)
            final_msg = "全部平倉訂單提交完成"
            logging.info(final_msg)
            return success, final_msg
        except Exception as e:
            error_msg = f"全部平倉異常：{str(e)}"
            logging.error(error_msg)
            return False, error_msg