from futu import *
import logging
from .utils import PENDING_ORDERS
from futu.common.constant import RET_OK  # 添加這行

class CancelOrder:
    def __init__(self, trd_ctx, trd_env):
        self.trd_ctx = trd_ctx
        self.trd_env = trd_env

    def execute(self, order_id):
        """取消指定訂單編號的待成交訂單"""
        try:
            futu_order_id = next((fid for fid, order in PENDING_ORDERS.items() if order['id'] == order_id), None)
            if not futu_order_id:
                error_msg = f"未找到訂單ID為 {order_id} 的待成交訂單"
                logging.error(error_msg)
                return False, error_msg

            ret, data = self.trd_ctx.modify_order(
                modify_order_op=ModifyOrderOp.CANCEL,
                order_id=futu_order_id,
                qty=0,
                price=0,
                trd_env=self.trd_env
            )
            if ret == RET_OK:
                success_msg = f"訂單 {order_id} 取消提交成功"
                logging.info(success_msg)
                if futu_order_id in PENDING_ORDERS:
                    del PENDING_ORDERS[futu_order_id]
                    # logging.info(f"移除監控訂單 {futu_order_id}，當前 PENDING_ORDERS: {PENDING_ORDERS}")
                return True, success_msg
            else:
                error_msg = f"訂單 {order_id} 取消失敗：{data}"
                logging.error(error_msg)
                return False, error_msg
        except Exception as e:
            error_msg = f"訂單 {order_id} 取消異常：{e}"
            logging.error(error_msg)
            return False, error_msg