from datetime import datetime
import logging

class Point:
    """管理單個點位的交易邏輯"""

    def __init__(self, point_data, logger, point_id):
        """初始化點位數據"""
        self.id = point_data.get('point_id', point_id)
        self.type = point_data.get('type', '')
        self.hit_price = float(point_data.get('hit_price', 0.0))
        self.allow_hit = point_data.get('allow_hit', True)
        self.allow_entry = point_data.get('allow_entry', True)
        self.qty_each_time = int(point_data.get('qty_each_time', 1))
        self.quantity_limits = int(point_data.get('quantity_limits', 10))
        self.orders = point_data.get('orders', [])
        self.hit_count = 0
        self.hit_limit = int(point_data.get('hit_limit', 10))
        self.trade_count = 0
        self.total_quantity = 0
        self.open_positions = []  # 儲存當前持倉
        self.total_pnl = 0.0
        self.trade_history = []  # 記錄歷史交易
        self.logger = logger
        self.point_id = point_id
        self.opened_indices = set()  # 記錄已開過的索引
        self.quantity_limit_notified = False  # 添加標誌，預設為 False

    def can_open_position(self, order_index):
        """檢查是否可以開倉"""
        if not self.allow_entry:
            self.logger.info(f"點位 {self.id} 不允許開倉")
            return False
        if order_index >= len(self.orders):
            self.logger.error(f"點位 {self.id} 無效訂單索引 {order_index}")
            return False
        if order_index in self.opened_indices:  # 檢查是否已開過該索引
            # self.logger.info(f"點位 {self.id} 索引 {order_index} 已開過倉，跳過")
            return False
        if self.hit_count >= self.hit_limit:
            self.logger.info(f"點位 {self.id} 已達最大命中次數 {self.hit_limit}")
            return False
        if self.total_quantity + self.qty_each_time > self.quantity_limits:
            if not self.quantity_limit_notified:  # 僅在第一次觸發時通知
                self.logger.info(f"點位 {self.id} 已達總數量限制 {self.quantity_limits}")
                self.quantity_limit_notified = True  # 設置標誌，避免重複通知
            return False
        order = self.orders[order_index]
        if order.get('quantity', 0) != self.qty_each_time:
            self.logger.warning(f"點位 {self.id} 訂單 {order_index} 數量 {order.get('quantity')} 與每次開倉數量 {self.qty_each_time} 不一致")
        return True

    def add_position(self, order_id, order_index, entry_price, custom_order_id):
        """記錄新開倉訂單"""
        order = self.orders[order_index].copy()
        if self.total_quantity + order.get('quantity', 0) > self.quantity_limits:
            self.logger.info(f"點位 {self.id} 已達總數量限制 {self.quantity_limits}，無法添加訂單 {order_id}")
            return False
        for pos in self.open_positions:
            if pos.get('order_id') == order_id:
                self.logger.info(f"訂單 {order_id} 已存在於點位 {self.id}，忽略重複添加")
                return False
        order['order_id'] = order_id
        order['custom_order_id'] = custom_order_id
        order['order_index'] = order_index
        order['entry_price'] = float(entry_price)
        self.open_positions.append(order)
        self.trade_count += 1
        self.total_quantity += order.get('quantity', 0)
        self.opened_indices.add(order_index)  # 記錄已開過的索引
        self.logger.info(f"點位 {self.id} 新增開倉訂單 {order_id}，索引 {order_index}，總數量 {self.total_quantity}/{self.quantity_limits} 次數")
        return True

    def close_position(self, order_id, exit_price):
        """關閉指定訂單並計算盈虧"""
        for pos in self.open_positions[:]:
            if pos.get('order_id') == order_id:
                quantity = pos.get('quantity', 0)
                entry_price = pos.get('entry_price', 0.0)
                direction = pos.get('direction', 'long')
                pnl = (exit_price - entry_price) * quantity if direction == 'long' else (entry_price - exit_price) * quantity
                self.total_pnl += pnl
                self.trade_history.append({
                    'order_id': order_id,
                    'entry_price': entry_price,
                    'exit_price': exit_price,
                    'quantity': quantity,
                    'direction': direction,
                    'pnl': pnl,
                    'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
                self.open_positions.remove(pos)
                self.total_quantity -= quantity
                self.logger.info(f"點位 {self.id} 關閉訂單 {order_id}，盈虧 {pnl}，剩餘總數量 {self.total_quantity}")
                return True
        self.logger.error(f"點位 {self.id} 未找到訂單 {order_id}")
        return False

    def update_pnl(self, current_price):
        """更新浮動盈虧"""
        self.total_pnl = 0.0
        for pos in self.open_positions:
            quantity = pos.get('quantity', 0)
            entry_price = pos.get('entry_price', 0.0)
            direction = pos.get('direction', 'long')
            pnl = (current_price - entry_price) * quantity if direction == 'long' else (entry_price - current_price) * quantity
            self.total_pnl += pnl
        self.logger.debug(f"點位 {self.id} 更新浮動盈虧：{self.total_pnl}")

    def check_hit(self, current_price):
        """檢查是否命中點位，誤差範圍 ±2"""
        if not self.allow_hit:
            self.logger.info(f"點位 {self.id} 不允許命中")
            return False
        tolerance = 2.0
        if self.hit_price - tolerance <= current_price <= self.hit_price + tolerance:
            self.hit_count += 1
            self.logger.info(f"點位 {self.id} 命中，當前命中次數 {self.hit_count}")
            return self.hit_count <= self.hit_limit
        return False

    def update_trailing_take_profit(self, order_id, current_price):
        """更新移動止盈，僅適用於 trailing_stop 策略"""
        for pos in self.open_positions:
            if pos.get('order_id') == order_id and pos.get('strategy', '') in ['trailing_stop', 'daily_trailing_stop', 'midlong_trailing_stop']:
                trail_offset = pos.get('trail_offset', 50.0)
                if pos.get('direction') == 'long':
                    new_take_profit = current_price - trail_offset
                    if new_take_profit > pos.get('take_profit', 0.0):
                        pos['take_profit'] = new_take_profit
                        self.logger.info(f"點位 {self.id} 訂單 {order_id} 更新移動止盈至 {new_take_profit}")
                else:
                    new_take_profit = current_price + trail_offset
                    if new_take_profit < pos.get('take_profit', 0.0):
                        pos['take_profit'] = new_take_profit
                        self.logger.info(f"點位 {self.id} 訂單 {order_id} 更新移動止盈至 {new_take_profit}")

    def get_status(self):
        """返回點位當前狀態"""
        return {
            'point_id': self.id,
            'type': self.type,
            'hit_price': self.hit_price,
            'hit_count': self.hit_count,
            'hit_limit': self.hit_limit,
            'allow_hit': self.allow_hit,
            'allow_entry': self.allow_entry,
            'qty_each_time': self.qty_each_time,
            'quantity_limits': self.quantity_limits,
            'trade_count': self.trade_count,
            'total_quantity': self.total_quantity,
            'total_pnl': self.total_pnl,
            'open_positions': len(self.open_positions),
            'orders': self.orders,
            'opened_indices': list(self.opened_indices)  # 回傳已開過的索引
        }