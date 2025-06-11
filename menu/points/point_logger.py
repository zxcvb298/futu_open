import os
from datetime import datetime

def append_to_point_log(point_id, message):
    """將訊息寫入點位專屬的 trade.log"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        while base_dir.endswith('points'):
            base_dir = os.path.dirname(base_dir)
        log_path = os.path.join(base_dir, 'points', point_id, 'trade.log')
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_line = f"{timestamp} - {message}\n"
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(log_line)
    except Exception as e:
        print(f"寫入 {point_id}/trade.log 失敗：{e}")

def update_point_history(point_id, order_id, message, is_open=True):
    """更新點位專屬的 trade_history.log"""
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        while base_dir.endswith('points'):
            base_dir = os.path.dirname(base_dir)
        log_path = os.path.join(base_dir, 'points', point_id, 'trade_history.log')
        temp_file = os.path.join(base_dir, 'points', point_id, 'trade_history_temp.log')
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        if not os.path.exists(log_path):
            with open(log_path, 'w', encoding='utf-8') as f:
                pass

        if is_open:
            log_line = f"{timestamp} - 開倉訂單：{message}\n"
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(log_line)
        else:
            with open(log_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            with open(temp_file, 'w', encoding='utf-8') as f:
                for line in lines:
                    if order_id not in line:
                        f.write(line)
            os.replace(temp_file, log_path)
    except Exception as e:
        print(f"更新 {point_id}/trade_history.log 失敗：{e}")