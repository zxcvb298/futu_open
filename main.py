from futu import *
from futu.common.constant import RET_OK
from menu.utils import PENDING_ORDERS, load_config, setup_logging, save_virtual_orders_to_csv, load_virtual_orders_from_csv, append_open_order_to_log, update_order_in_log, VIRTUAL_ORDERS, CLOSING_ORDERS
from menu.open_order import OpenOrder
from menu.close_order import CloseOrder
from menu.get_positions import GetPositions
from menu.close_all_orders import CloseAllOrders
from menu.cancel_order import CancelOrder
from menu.monitor_stop_loss_take_profit import MonitorStopLossTakeProfit
from menu.points.point_manager import PointManager  # 引入 PointManager
import os
import time
import threading
import logging

'''
開倉：/open_order HK.MHI2505 long 1 market fix 或 /open_order HK.MHI2505 long 1 market trailing
     /open_order HK.MHI2505 long 1 23260 fix 或 /open_order HK.MHI2505 long 1 23260 trailing
     /open_order HK.MHI2505 long 1 23280 23270 23290
     /open_order HK.MHI2505 long 1 23280 或 /open_order HK.MHI2505 long 1 market
平倉：/force_order HSI-001 1 long market 或 /force_order HSI-001 1 long 23700.0
查詢持倉：/status
全部平倉：/close_all
取消交易：/cancel_order HSI-001
退出：exit
'''

class Main:
    """主交易系統，整合各功能類"""

    def __init__(self):
        # 載入配置
        config = load_config()
        self.quote_ctx = OpenQuoteContext(host=config['host'], port=config['port'])
        self.trd_ctx = OpenFutureTradeContext(host=config['host'], port=config['port'])
        self.trd_env = config['trd_env']
        setup_logging()
        # 載入虛擬訂單
        VIRTUAL_ORDERS[:] = load_virtual_orders_from_csv()
        # 初始化訂單計數器
        max_order_num = 0
        for order in VIRTUAL_ORDERS:
            try:
                order_num = int(order['id'].split('-')[1])
                max_order_num = max(max_order_num, order_num)
            except (IndexError, ValueError):
                continue

        # 初始化各功能
        self.open_order = OpenOrder(self.quote_ctx, self.trd_ctx, self.trd_env, max_order_num + 1)
        self.force_order = CloseOrder(self.quote_ctx, self.trd_ctx, self.trd_env)
        self.status = GetPositions(self.quote_ctx)
        self.close_all = CloseAllOrders(self.quote_ctx, self.trd_ctx, self.trd_env)
        self.cancel_order = CancelOrder(self.trd_ctx, self.trd_env)
        self.monitor_sl_tp = MonitorStopLossTakeProfit(self.quote_ctx, self.trd_ctx, self.trd_env)
        # 初始化點位管理
        self.point_manager = PointManager(self.quote_ctx, self.trd_ctx, self.trd_env, max_order_num + 1)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        self.point_manager.load_points(os.path.join(base_dir, 'points'))

    def monitor_orders(self):
        """監控訂單狀態並更新持倉"""
        while True:
            try:
                for order_id in list(PENDING_ORDERS.keys()):
                    ret, data = self.trd_ctx.order_list_query(order_id=order_id, trd_env=self.trd_env)
                    if ret == RET_OK and not data.empty:
                        status = data['order_status'][0]
                        order_info = PENDING_ORDERS.get(order_id, {})
                        custom_order_id = order_info.get('id', '未知')
                        code = order_info.get('code', '未知')
                        direction = order_info.get('direction', '未知')
                        qty = order_info.get('qty', 0)
                        price = order_info.get('price', 0)
                        order_type = order_info.get('order_type', 'open')
                        stop_loss = order_info.get('stop_loss')
                        take_profit = order_info.get('take_profit')
                        use_trailing = order_info.get('use_trailing', False)
                        point_id = order_info.get('point_id')
                        hit_price = order_info.get('hit_price')

                        if status == OrderStatus.FILLED_ALL:
                            if order_type == 'open':
                                VIRTUAL_ORDERS.append({
                                    'id': custom_order_id,
                                    'code': code,
                                    'direction': direction,
                                    'quantity': qty,
                                    'entry_price': price,
                                    'is_open': True,
                                    'stop_loss': stop_loss,
                                    'take_profit': take_profit,
                                    'highest_price': price,
                                    'lowest_price': price,
                                    'use_trailing': use_trailing,
                                    'is_closing': False
                                })
                                logging.info(f"📥 開倉訂單成功成交：訂單ID={custom_order_id}, 合約={code}, 方向={direction}, 數量={qty}, 開倉價格={price}, 命中點位 ({[point_id]})={hit_price}, "
                                                f"止損={stop_loss or '無'}, 止盈={take_profit or '無'}, 移動止盈={'啟用' if use_trailing else '未啟用'}\n")
                                append_open_order_to_log(custom_order_id, code, direction, qty, price)
                                # 檢查是否為自動開倉訂單，更新點位記錄
                                if custom_order_id.startswith("AUTO-"):
                                    point_id = custom_order_id.split('-')[1]
                                    for point in self.point_manager.points.values():
                                        if point.id == point_id:
                                            point.add_position(order_id, int(custom_order_id.split('-')[2]), price, custom_order_id)
                                            from menu.points.point_logger import update_point_history
                                            update_point_history(point_id, order_id, f"合約={code}, 方向={direction}, 數量={qty}, 價格={price}", is_open=True)
                            else:
                                original_qty = qty
                                remaining_qty = 0
                                for order in VIRTUAL_ORDERS[:]:
                                    if order['id'] == custom_order_id and order['direction'] == direction and order['is_open']:
                                        if order['quantity'] <= qty:
                                            order['is_open'] = False
                                            order['is_closing'] = False
                                            qty -= order['quantity']
                                        else:
                                            order['quantity'] -= qty
                                            remaining_qty = order['quantity']
                                            order['is_closing'] = False
                                            qty = 0
                                        break
                                VIRTUAL_ORDERS[:] = [order for order in VIRTUAL_ORDERS if order['is_open'] and order['quantity'] > 0]
                                entry_price = order_info.get('entry_price', 0)
                                pnl = (price - entry_price) * original_qty * 10 if direction == 'long' else (entry_price - price) * original_qty * 10
                                logging.info(f"📤 平倉訂單成功成交：訂單ID={custom_order_id}, 合約={code}, 方向={direction}, 數量={original_qty}, 平倉價格={price}, 盈虧={pnl}\n")
                                update_order_in_log(custom_order_id, remaining_qty)
                                if custom_order_id in CLOSING_ORDERS:
                                    CLOSING_ORDERS.remove(custom_order_id)
                                # 檢查是否為自動開倉訂單，更新點位記錄
                                if custom_order_id.startswith("AUTO-"):
                                    point_id = custom_order_id.split('-')[1]
                                    for point in self.point_manager.points.values():
                                        if point.id == point_id:
                                            point.close_position(order_id, price)
                                            from menu.points.point_logger import update_point_history
                                            update_point_history(point_id, order_id, f"合約={code}, 方向={direction}, 數量={qty}, 價格={price}", is_open=False)
                            del PENDING_ORDERS[order_id]
                        elif status in [OrderStatus.CANCELLED_ALL, OrderStatus.FAILED]:
                            logging.info(f"訂單 {custom_order_id} 已取消或失敗")
                            del PENDING_ORDERS[order_id]
                            if custom_order_id in CLOSING_ORDERS:
                                CLOSING_ORDERS.remove(custom_order_id)
                                for order in VIRTUAL_ORDERS:
                                    if order['id'] == custom_order_id and not order['is_open']:
                                        order['is_open'] = True
                                        order['is_closing'] = False
                                        if order['use_trailing']:
                                            current_price = self.monitor_sl_tp.get_market_price(order['code'])
                                            if current_price:
                                                order['highest_price'] = current_price
                                                order['lowest_price'] = current_price
                                            else:
                                                order['highest_price'] = order['entry_price']
                                                order['lowest_price'] = order['entry_price']
                                        logging.warning(f"恢復訂單 {custom_order_id} 為可監控狀態，因平倉取消或失敗")
                time.sleep(1)
            except Exception as e:
                logging.error(f"訂單監控異常：{e}")
                time.sleep(5)

    def parse_command(self, command):
        """解析終端命令並執行"""
        parts = command.strip().split()
        if not parts:
            error_msg = "無效命令"
            logging.info(error_msg)
            return error_msg

        cmd = parts[0].lower()
        if cmd == '/open_order' and len(parts) >= 4:
            code = parts[1]
            direction = parts[2]
            try:
                qty = int(parts[3])
                if len(parts) == 6:
                    price = parts[4] if parts[4].lower() not in ['fix', 'trailing'] else 'market'
                    price = float(price) if price != 'market' else price
                    mode = parts[5].lower() if len(parts) > 5 else None
                    use_fix = (mode == 'fix')
                    use_trailing = (mode == 'trailing')
                    if mode not in ['fix', 'trailing', None]:
                        error_msg = "無效模式，應為 'fix' 或 'trailing'"
                        logging.info(error_msg)
                        return error_msg
                    success, msg = self.open_order.execute(code, direction, qty, price, use_fix=use_fix, use_trailing=use_trailing)
                elif len(parts) == 7:
                    price = float(parts[4])
                    stop_loss = float(parts[5])
                    take_profit = float(parts[6])
                    success, msg = self.open_order.execute(code, direction, qty, price, stop_loss=stop_loss, take_profit=take_profit)
                else:
                    price = parts[4] if len(parts) > 4 else 'market'
                    price = float(price) if price != 'market' else price
                    success, msg = self.open_order.execute(code, direction, qty, price)
                return msg
            except ValueError:
                error_msg = "數量、價格、止損或止盈格式錯誤"
                logging.info(error_msg)
                return error_msg
        elif cmd == '/force_order' and len(parts) >= 4:
            order_id = parts[1]
            try:
                qty = int(parts[2])
                direction = parts[3]
                price = float(parts[4]) if len(parts) > 4 and parts[4].lower() != 'market' else None
                success, _, _, _, msg = self.force_order.execute(order_id, qty, direction, price)
                return msg
            except ValueError:
                error_msg = "數量或價格格式錯誤"
                logging.info(error_msg)
                return error_msg
        elif cmd == '/cancel_order' and len(parts) == 2:
            order_id = parts[1]
            success, msg = self.cancel_order.execute(order_id)
            return msg
        elif cmd == '/status':
            success, msg = self.status.execute()
            return msg
        elif cmd == '/close_all':
            success, msg = self.close_all.execute()
            return msg
        else:
            error_msg = "無效命令或參數不足"
            logging.info(error_msg)
            return error_msg

    def run(self):
        """啟動終端交互界面"""
        monitor_thread = threading.Thread(target=self.monitor_orders, daemon=True)
        monitor_thread.start()
        sl_tp_thread = threading.Thread(target=self.monitor_sl_tp.monitor, daemon=True)
        sl_tp_thread.start()
        # 啟動點位監控
        point_thread = threading.Thread(target=self.point_manager.start_monitor, daemon=True)
        point_thread.start()

        logging.info("期貨交易系統已啟動，輸入命令（/open_order, /force_order, /status, /close_all, /cancel_order），輸入 'exit' 退出")
        while True:
            command = input("").strip()
            if command.lower() == 'exit':
                logging.info("退出系統")
                self.point_manager.running = False  # 停止點位監控
                save_virtual_orders_to_csv()
                self.quote_ctx.close()
                self.trd_ctx.close()
                break
            result = self.parse_command(command)

if __name__ == "__main__":
    trading = Main()
    trading.run()