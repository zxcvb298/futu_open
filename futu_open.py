import logging
import time
import threading
import os
import shutil
import re
import retrying
import csv
from datetime import datetime
from futu import *

'''
開倉：/open_order HK.MHI2505 long 1 market 或 /open_order HK.MHI2505 long 1 23625.0
平倉：/force_order HSI-001 1 long market 或 /force_order HSI-001 1 long 23700.0
查詢持倉：/status
全部平倉：/close_all
取消交易：/cancel_order HSI-001 (未完成)
退出：exit (要用exit退出，才會保存csv)

cohfig中 "trd_env": "SIMULATE" 模擬交易，"trd_env": "REAL" 真實交易
'''

PENDING_ORDERS = {}  # 待成交訂單：{futu_order_id: order_info}
VIRTUAL_ORDERS = []  # 開倉記錄：[{order_info}]

def load_config():
    """從 config.json 載入配置，若失敗則使用預設值"""
    default_config = {
        'host': '127.0.0.1',
        'port': 11111,
        'trd_env': TrdEnv.SIMULATE
    }
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        # 驗證必要欄位
        if not all(key in config for key in ['host', 'port', 'trd_env']):
            logging.error("config.json 缺少必要欄位，使用預設配置")
            return default_config
        # 映射 trd_env 字串到 TrdEnv 枚舉
        trd_env_map = {'REAL': TrdEnv.REAL, 'SIMULATE': TrdEnv.SIMULATE}
        config['trd_env'] = trd_env_map.get(config['trd_env'].upper(), TrdEnv.SIMULATE)
        return config
    except FileNotFoundError:
        logging.warning("config.json 不存在，使用預設配置")
        return default_config
    except json.JSONDecodeError:
        logging.error("config.json 格式錯誤，使用預設配置")
        return default_config
    except Exception as e:
        logging.error(f"載入 config.json 失敗：{e}，使用預設配置")
        return default_config

def setup_logging():
    """設置日誌，輸出到 trade.log 和控制台"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        handlers=[
            logging.FileHandler('trade.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

def save_virtual_orders_to_csv():
    """將尚未平倉的虛擬訂單保存到 virtual_orders.csv"""
    try:
        csv_file = 'menu/virtual_orders.csv'
        if not os.access(os.path.dirname(csv_file) or '.', os.W_OK):
            logging.error("沒有寫入 virtual_orders.csv 的權限，請檢查目錄權限或以管理員身份運行")
            return
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['id', 'code', 'direction', 'quantity', 'entry_price', 'is_open']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for order in VIRTUAL_ORDERS:
                if order['is_open'] and order['quantity'] > 0:
                    writer.writerow({
                        'id': order['id'],
                        'code': order['code'],
                        'direction': order['direction'],
                        'quantity': order['quantity'],
                        'entry_price': order['entry_price'],
                        'is_open': order['is_open']
                    })
        logging.info(f"成功保存 {sum(1 for o in VIRTUAL_ORDERS if o['is_open'] and o['quantity'] > 0)} 筆虛擬訂單到 virtual_orders.csv")
    except Exception as e:
        logging.error(f"保存 virtual_orders.csv 失敗：{e}")

def load_virtual_orders_from_csv():
    """從 virtual_orders.csv 載入虛擬訂單到 VIRTUAL_ORDERS"""
    try:
        csv_file = 'menu/virtual_orders.csv'
        if not os.path.exists(csv_file):
            logging.info("virtual_orders.csv 不存在，啟動時無虛擬訂單")
            return []
        orders = []
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    order = {
                        'id': row['id'],
                        'code': row['code'],
                        'direction': row['direction'],
                        'quantity': int(row['quantity']),
                        'entry_price': float(row['entry_price']),
                        'is_open': row['is_open'].lower() == 'true'
                    }
                    orders.append(order)
                except (KeyError, ValueError) as e:
                    logging.error(f"解析 virtual_orders.csv 行失敗，跳過：{row}，錯誤：{e}")
        logging.info(f"成功載入 {len(orders)} 筆虛擬訂單從 virtual_orders.csv")
        return orders
    except Exception as e:
        logging.error(f"載入 virtual_orders.csv 失敗：{e}")
        return []

def append_open_order_to_log(order_id, code, direction, qty, price):
    """將開倉訂單成交記錄追加到 open_orders.log"""
    try:
        # 使用 datetime 生成毫秒級時間戳
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
        direction_text = '多' if direction.lower() == 'long' else '空'
        log_line = f"{timestamp} ID: {order_id} 提交訂單：合約={code}, 方向={direction_text}, 數量={qty}, 價格={price}\n"
        with open('menu/open_orders.log', 'a', encoding='utf-8') as f:
            f.write(log_line)
    except Exception as e:
        logging.error(f"寫入 open_orders.log 失敗，訂單ID={order_id}：{e}")

@retrying.retry(stop_max_attempt_number=3, wait_fixed=1000)
def update_order_in_log(order_id, remaining_qty):
    """更新或移除 open_orders.log 中指定訂單的數量"""
    try:
        temp_file = 'open_orders_temp.log'
        log_updated = False
        if not os.path.exists('menu/open_orders.log'):
            logging.warning(f"open_orders.log 不存在，無需更新訂單 {order_id}")
            return
        with open('menu/open_orders.log', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(temp_file, 'w', encoding='utf-8') as f:
            for line in lines:
                if f"ID: {order_id} " in line:
                    if remaining_qty > 0:
                        # 更新數量
                        updated_line = re.sub(r'數量=\d+', f'數量={remaining_qty}', line)
                        f.write(updated_line)
                    # 如果數量為 0，跳過該行（移除）
                    log_updated = True
                else:
                    f.write(line)
        if not log_updated:
            logging.warning(f"open_orders.log 中未找到訂單 {order_id} 的記錄")
        # 檢查寫入權限
        if not os.access(os.path.dirname(temp_file) or '.', os.W_OK):
            logging.error("沒有寫入 open_orders.log 的權限，請檢查目錄權限或以管理員身份運行")
            raise PermissionError("沒有寫入 open_orders.log 的權限")
        shutil.move(temp_file, 'menu/open_orders.log')
    except Exception as e:
        logging.error(f"更新 open_orders.log 中訂單 {order_id} 失敗：{e}")
        raise

class FuturesTrading:
    """簡化期貨交易類"""
    def __init__(self):
        config = load_config()
        self.quote_ctx = OpenQuoteContext(host=config['host'], port=config['port'])
        self.trd_ctx = OpenFutureTradeContext(host=config['host'], port=config['port'])
        self.TRD_ENV = config['trd_env']
        setup_logging()
        # 載入虛擬訂單
        global VIRTUAL_ORDERS
        VIRTUAL_ORDERS = load_virtual_orders_from_csv()
        # 初始化訂單計數器，基於最大訂單 ID
        max_order_num = 0
        for order in VIRTUAL_ORDERS:
            try:
                order_num = int(order['id'].split('-')[1])
                max_order_num = max(max_order_num, order_num)
            except (IndexError, ValueError):
                continue
        self.order_counter_open = max_order_num + 1

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

    def place_order(self, code, direction, qty, price=None):
        """提交開倉訂單"""
        try:
            if price is None:
                price = self.get_market_price(code)
                if price is None:
                    error_msg = "無法獲取市場價格"
                    logging.error(error_msg)
                    return False, error_msg

            custom_order_id = f"HSI-{self.order_counter_open:03d}"
            self.order_counter_open += 1
            trd_side = TrdSide.BUY if direction.lower() == 'long' else TrdSide.SELL

            ret, data = self.trd_ctx.place_order(
                price=price,
                qty=qty,
                code=code,
                trd_side=trd_side,
                trd_env=self.TRD_ENV,
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

    def close_order(self, order_id, qty, direction, price=None):
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
                trd_env=self.TRD_ENV,
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

    def close_all_orders(self):
        """平倉所有當前持倉的虛擬訂單"""
        try:
            if not any(order['is_open'] and order['quantity'] > 0 for order in VIRTUAL_ORDERS):
                logging.info("無持倉可平倉")
                return False, "無持倉可平倉"

            results = []
            for order in VIRTUAL_ORDERS:
                if order['is_open'] and order['quantity'] > 0:
                    success, _, _, _, msg = self.close_order(
                        order_id=order['id'],
                        qty=order['quantity'],
                        direction=order['direction'],
                        price=None  # 使用市場價格
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

    def cancel_order(self, order_id):
        """取消指定訂單編號的待成交訂單"""
        try:
            # 查找對應的 futu_order_id
            futu_order_id = next((fid for fid, order in PENDING_ORDERS.items() if order['id'] == order_id), None)
            if not futu_order_id:
                error_msg = f"未找到訂單ID為 {order_id} 的待成交訂單"
                logging.error(error_msg)
                return False, error_msg

            # 嘗試取消訂單
            ret, data = self.trd_ctx.modify_order(
                modify_order_op=ModifyOrderOp.CANCEL,
                order_id=futu_order_id,
                qty=0,  # 取消訂單設置 qty=0
                price=0,  # 取消訂單設置 price=0
                trd_env=self.TRD_ENV
            )
            if ret == RET_OK:
                success_msg = f"訂單 {order_id} 取消提交成功"
                logging.info(success_msg)
                # 移除監控
                if futu_order_id in PENDING_ORDERS:
                    del PENDING_ORDERS[futu_order_id]
                return True, success_msg
            else:
                error_msg = f"訂單 {order_id} 取消失敗：{data}"
                logging.error(error_msg)
                return False, error_msg
        except Exception as e:
            error_msg = f"訂單 {order_id} 取消異常：{e}"
            logging.error(error_msg)
            return False, error_msg

    def get_positions(self):
        """查詢並記錄當前虛擬訂單和待成交訂單"""
        try:
            has_positions = False

            # 顯示成功開倉的訂單（VIRTUAL_ORDERS）
            if VIRTUAL_ORDERS:
                logging.info("=== 當前持倉 ===")
                for order in VIRTUAL_ORDERS:
                    if order['is_open'] and order['quantity'] > 0:
                        direction_text = '多' if order['direction'] == 'long' else '空'
                        # 計算浮動盈虧
                        current_price = self.get_market_price(order['code'])
                        if current_price is not None:
                            if order['direction'] == 'long':
                                pnl = (current_price - order['entry_price']) * order['quantity'] * 10
                            else:  # short
                                pnl = (order['entry_price'] - current_price) * order['quantity'] * 10
                            pnl_text = f"{pnl:.2f}"
                        else:
                            pnl_text = "無法計算盈虧"
                        logging.info(f"ID: {order['id']}, 合約={order['code']}, 方向={direction_text}, "
                                     f"數量={order['quantity']}, 價格={order['entry_price']}, 浮動盈虧={pnl_text}")
                        has_positions = True

            # 顯示待成交訂單（PENDING_ORDERS）
            if PENDING_ORDERS:
                logging.info("=== 待成交訂單 ===")
                for futu_order_id, order in PENDING_ORDERS.items():
                    direction_text = '多' if order['direction'] == 'long' else '空'
                    order_type_text = '開倉' if order['order_type'] == 'open' else '平倉'
                    logging.info(f"ID: {order['id']}, 合約={order['code']}, 方向={direction_text}, "
                                 f"數量={order['qty']}, 價格={order['price']}, 類型={order_type_text}")
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

    def monitor_orders(self):
        """監控訂單狀態並更新持倉"""
        while True:
            try:
                for order_id in list(PENDING_ORDERS.keys()):
                    ret, data = self.trd_ctx.order_list_query(order_id=order_id, trd_env=self.TRD_ENV)
                    if ret == RET_OK and not data.empty:
                        status = data['order_status'][0]
                        order_info = PENDING_ORDERS.get(order_id, {})
                        custom_order_id = order_info.get('id', '未知')
                        code = order_info.get('code', '未知')
                        direction = order_info.get('direction', '未知')
                        qty = order_info.get('qty', 0)
                        price = order_info.get('price', 0)
                        order_type = order_info.get('order_type', 'open')

                        if status == OrderStatus.FILLED_ALL:
                            if order_type == 'open':
                                VIRTUAL_ORDERS.append({
                                    'id': custom_order_id,
                                    'code': code,
                                    'direction': direction,
                                    'quantity': qty,
                                    'entry_price': price,
                                    'is_open': True
                                })
                                logging.info(f"開倉訂單成功成交：訂單ID={custom_order_id}, 合約={code}, 方向={direction}, 數量={qty}, 開倉價格={price}")
                                # 記錄到 open_orders.log
                                append_open_order_to_log(custom_order_id, code, direction, qty, price)
                            else:  # 平倉訂單
                                original_qty = qty  # 儲存原始平倉數量
                                remaining_qty = 0
                                for order in VIRTUAL_ORDERS[:]:
                                    if order['id'] == custom_order_id and order['direction'] == direction and order['is_open']:
                                        if order['quantity'] <= qty:
                                            order['is_open'] = False
                                            qty -= order['quantity']
                                        else:
                                            order['quantity'] -= qty
                                            remaining_qty = order['quantity']
                                            qty = 0
                                        break
                                VIRTUAL_ORDERS[:] = [order for order in VIRTUAL_ORDERS if order['is_open'] and order['quantity'] > 0]
                                entry_price = order_info.get('entry_price', 0)
                                pnl = (entry_price - price) * original_qty * 10 if direction == 'long' else (price - entry_price) * original_qty * 10
                                logging.info(f"平倉訂單成功成交：訂單ID={custom_order_id}, 合約={code}, 方向={direction}, 數量={original_qty}, 平倉價格={price}, 盈虧={pnl}")
                                # 更新 open_orders.log
                                update_order_in_log(custom_order_id, remaining_qty)
                            del PENDING_ORDERS[order_id]
                        elif status in [OrderStatus.CANCELLED_ALL, OrderStatus.FAILED]:
                            logging.info(f"訂單 {custom_order_id} 已取消或失敗")
                            del PENDING_ORDERS[order_id]
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
                price = float(parts[4]) if len(parts) > 4 and parts[4].lower() != 'market' else None
                success, msg = self.place_order(code, direction, qty, price)
                return msg
            except ValueError:
                error_msg = "數量或價格格式錯誤"
                logging.info(error_msg)
                return error_msg
        elif cmd == '/force_order' and len(parts) >= 4:
            order_id = parts[1]
            try:
                qty = int(parts[2])
                direction = parts[3]
                price = float(parts[4]) if len(parts) > 4 and parts[4].lower() != 'market' else None
                success, _, _, _, msg = self.close_order(order_id, qty, direction, price)
                return msg
            except ValueError:
                error_msg = "數量或價格格式錯誤"
                logging.info(error_msg)
                return error_msg
        elif cmd == '/cancel_order' and len(parts) == 2:
            order_id = parts[1]
            success, msg = self.cancel_order(order_id)
            return msg
        elif cmd == '/status':
            success, msg = self.get_positions()
            return msg
        elif cmd == '/close_all':
            success, msg = self.close_all_orders()
            return msg
        else:
            error_msg = "無效命令或參數不足"
            logging.info(error_msg)
            return error_msg

    def run(self):
        """啟動終端交互界面"""
        monitor_thread = threading.Thread(target=self.monitor_orders, daemon=True)
        monitor_thread.start()

        logging.info("期貨交易系統已啟動，輸入命令（/open_order, /force_order, /status, /close_all, /cancel_order），輸入 'exit' 退出")
        while True:
            command = input("").strip()
            if command.lower() == 'exit':
                logging.info("退出系統")
                save_virtual_orders_to_csv()  # 保存虛擬訂單
                self.quote_ctx.close()
                self.trd_ctx.close()
                break
            result = self.parse_command(command)

if __name__ == "__main__":
    trading = FuturesTrading()
    trading.run()

'''
開倉：/open_order HK.MHI2505 long 1 market 或 /open_order HK.MHI2505 long 1 23625.0
平倉：/force_order HSI-001 1 long market 或 /force_order HSI-001 1 long 23700.0
查詢持倉：/status
全部平倉：/close_all
取消交易：/cancel_order HSI-001 (未完成)
退出：exit (要用exit退出，才會保存csv)

cohfig中 "trd_env": "SIMULATE" 模擬交易，"trd_env": "REAL" 真實交易
'''