import json
import logging
import os
import shutil
import re
import retrying
import csv
from datetime import datetime
from futu import *

# 全局變數
PENDING_ORDERS = {}  # 待成交訂單：{futu_order_id: order_info}
VIRTUAL_ORDERS = []  # 開倉記錄：[{order_info}]
CLOSING_ORDERS = set()  # 正在平倉的訂單 ID
TRAILING_THRESHOLD = 100  # 預設移動止盈閾值
FIXED_THRESHOLD = 100  # 預設固定止盈止損閾值

def load_config():
    """從 config.json 載入配置，若失敗則使用預設值"""
    default_config = {
        'host': '127.0.0.1',
        'port': 11111,
        'trd_env': TrdEnv.SIMULATE,
        'trailing_threshold': 100,
        'fixed_threshold': 100
    }
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        while base_dir.endswith('menu'):
            base_dir = os.path.dirname(base_dir)
        config_path = os.path.join(base_dir, 'config.json')
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        if not all(key in config for key in ['host', 'port', 'trd_env']):
            logging.error("config.json 缺少必要欄位，使用預設配置")
            return default_config
        trd_env_map = {'REAL': TrdEnv.REAL, 'SIMULATE': TrdEnv.SIMULATE}
        config['trd_env'] = trd_env_map.get(config['trd_env'].upper(), TrdEnv.SIMULATE)
        # 更新全局 TRAILING_THRESHOLD 和 FIXED_THRESHOLD
        global TRAILING_THRESHOLD, FIXED_THRESHOLD
        TRAILING_THRESHOLD = float(config.get('trailing_threshold', default_config['trailing_threshold']))
        FIXED_THRESHOLD = float(config.get('fixed_threshold', default_config['fixed_threshold']))
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
    base_dir = os.path.dirname(os.path.abspath(__file__))
    while base_dir.endswith('menu'):
        base_dir = os.path.dirname(base_dir)
    log_path = os.path.join(base_dir, 'trade.log')
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        handlers=[
            logging.FileHandler(log_path, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )

def save_virtual_orders_to_csv():
    """將尚未平倉的虛擬訂單保存到 virtual_orders.csv"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        while base_dir.endswith('menu'):
            base_dir = os.path.dirname(base_dir)
        csv_file = os.path.join(base_dir, 'virtual_orders.csv')
        if not os.access(os.path.dirname(csv_file) or '.', os.W_OK):
            logging.error("沒有寫入 virtual_orders.csv 的權限，請檢查目錄權限或以管理員身份運行")
            return
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['id', 'code', 'direction', 'quantity', 'entry_price', 'is_open', 'stop_loss', 'take_profit', 'highest_price', 'lowest_price', 'is_closing']
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
                        'is_open': order['is_open'],
                        'stop_loss': order.get('stop_loss', ''),
                        'take_profit': order.get('take_profit', ''),
                        'highest_price': order.get('highest_price', ''),
                        'lowest_price': order.get('lowest_price', ''),
                        'is_closing': order.get('is_closing', False)
                    })
        logging.info(f"成功保存 {sum(1 for o in VIRTUAL_ORDERS if o['is_open'] and o['quantity'] > 0)} 筆虛擬訂單到 virtual_orders.csv")
    except Exception as e:
        logging.error(f"保存 virtual_orders.csv 失敗：{e}")

def load_virtual_orders_from_csv():
    """從 virtual_orders.csv 載入虛擬訂單到 VIRTUAL_ORDERS"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        while base_dir.endswith('menu'):
            base_dir = os.path.dirname(base_dir)
        csv_file = os.path.join(base_dir, 'virtual_orders.csv')
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
                        'is_open': row['is_open'].lower() == 'true',
                        'stop_loss': float(row['stop_loss']) if row.get('stop_loss') and row['stop_loss'] else None,
                        'take_profit': float(row['take_profit']) if row.get('take_profit') and row['take_profit'] else None,
                        'highest_price': float(row['highest_price']) if row.get('highest_price') and row['highest_price'] else None,
                        'lowest_price': float(row['lowest_price']) if row.get('lowest_price') and row['lowest_price'] else None,
                        'is_closing': row.get('is_closing', 'false').lower() == 'true'
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
        base_dir = os.path.dirname(os.path.abspath(__file__))
        while base_dir.endswith('menu'):
            base_dir = os.path.dirname(base_dir)
        log_path = os.path.join(base_dir, 'open_orders.log')
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S,%f')[:-3]
        direction_text = '多' if direction.lower() == 'long' else '空'
        log_line = f"{timestamp} ID: {order_id} 提交訂單：合約={code}, 方向={direction_text}, 數量={qty}, 價格={price}\n"
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(log_line)
    except Exception as e:
        logging.error(f"寫入 open_orders.log 失敗，訂單ID={order_id}：{e}")

@retrying.retry(stop_max_attempt_number=3, wait_fixed=1000)
def update_order_in_log(order_id, remaining_qty):
    """更新或移除 open_orders.log 中指定訂單的數量"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        while base_dir.endswith('menu'):
            base_dir = os.path.dirname(base_dir)
        log_path = os.path.join(base_dir, 'open_orders.log')
        temp_file = os.path.join(base_dir, 'open_orders_temp.log')
        log_updated = False
        if not os.path.exists(log_path):
            logging.warning(f"open_orders.log 不存在，無需更新訂單 {order_id}")
            return
        with open(log_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        with open(temp_file, 'w', encoding='utf-8') as f:
            for line in lines:
                if f"ID: {order_id} " in line:
                    if remaining_qty > 0:
                        updated_line = re.sub(r'數量=\d+', f'數量={remaining_qty}', line)
                        f.write(updated_line)
                    log_updated = True
                else:
                    f.write(line)
        if not log_updated:
            logging.warning(f"open_orders.log 中未找到訂單 {order_id} 的記錄")
        if not os.access(os.path.dirname(temp_file) or '.', os.W_OK):
            logging.error("沒有寫入 open_orders.log 的權限，請檢查目錄權限或以管理員身份運行")
            raise PermissionError("沒有寫入 open_orders.log 的權限")
        shutil.move(temp_file, log_path)
    except Exception as e:
        logging.error(f"更新 open_orders.log 中訂單 {order_id} 失敗：{e}")
        raise