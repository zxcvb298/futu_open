import os
import json
import logging
import time
from futu.common.constant import RET_OK
from .point import Point
from ..open_order import OpenOrder
from ..close_order import CloseOrder

class PointManager:
    """管理所有點位並執行自動交易"""

    def __init__(self, quote_ctx, trd_ctx, trd_env, order_counter):
        """初始化點位管理器"""
        self.points = {}
        self.quote_ctx = quote_ctx
        self.open_order = OpenOrder(quote_ctx, trd_ctx, trd_env, order_counter)
        self.close_order = CloseOrder(quote_ctx, trd_ctx, trd_env)
        self.running = False

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

    def load_points(self, base_dir):
        """從指定資料夾加載所有點位 JSON 文件"""
        point_folders = ['DP1', 'DP2', 'DP3', 'DS1', 'DS2', 'DS3', 'MLP1', 'MLP2', 'MLP3', 'MLS1', 'MLS2', 'MLS3']
        for folder in point_folders:
            json_path = os.path.join(base_dir, folder, f"{folder}.json")
            if os.path.exists(json_path):
                try:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        points_data = json.load(f)
                    for point_data in points_data:
                        point_id = point_data.get('point_id', folder)
                        logger = logging.getLogger(f'trade_{point_id}')
                        self.points[point_id] = Point(point_data, logger, point_id)
                        logger.info(f"加載點位 {point_id} 從 {json_path}")
                except Exception as e:
                    logging.error(f"加載 {json_path} 失敗：{e}")
            else:
                logging.warning(f"JSON 文件 {json_path} 不存在，跳過")

    def start_monitor(self):
        """啟動點位監控"""
        self.running = True
        while self.running:
            current_price = self.get_market_price('HK.MHI2506')
            if current_price:
                for point_id, point in self.points.items():
                    hit_price = point.hit_price
                    for order in point.orders:
                        order_index = order.get('order_index', 0)
                        tolerance = 2.0
                        entry_price = order.get('entry_price', 0.0)
                        if (abs(current_price - entry_price) <= tolerance and
                            point.can_open_position(order_index)):
                            point.hit_limit += 1
                            # point.logger.info(f"點位 {point_id} 觸發開倉，當前價格 {current_price}, hit_price {hit_price}, entry_price {entry_price}")
                            self.open_position(point_id, order_index, entry_price, hit_price)
                    point.update_pnl(current_price)
                    for pos in point.open_positions:
                        point.update_trailing_take_profit(pos.get('order_id'), current_price)
            time.sleep(1)

    def open_position(self, point_id, order_index, entry_price, hit_price):
        """開倉指定點位的訂單"""
        if point_id not in self.points:
            logging.error(f"點位 {point_id} 不存在")
            return False
        point = self.points[point_id]
        if not point.can_open_position(order_index):
            return False
        order = point.orders[order_index]

        use_trailing = (point.trade_count % 2 == 1)
        if use_trailing:
            point.logger.info(f"點位 {point_id} 觸發開倉，第 {point.trade_count + 1} 次開倉，開倉價 {entry_price}，使用移動止盈")
        else:
            point.logger.info(f"點位 {point_id} 觸發開倉，第 {point.trade_count + 1} 次開倉，開倉價 {entry_price}，使用固定止盈")

        success, msg = self.open_order.execute(
            code='HK.MHI2506',
            direction=order.get('direction'),
            qty=order.get('quantity', point.qty_each_time),
            price=order.get('entry_price', 0.0),
            stop_loss=order.get('stop_loss'),
            take_profit=order.get('take_profit'),
            use_trailing=use_trailing,
            point_id=point_id,
            hit_price=hit_price
        )
        if success:
            order_id = msg.split('訂單ID=')[1].split(' ')[0]
            point.add_position(order_id, order_index, order.get('entry_price', 0.0), order_id)
            # point.logger.info(f"點位 {point_id} 提交開倉訂單 {order_id}")
        return success

    def close_position(self, point_id, order_id=None):
        """平倉指定點位或訂單"""
        if point_id not in self.points:
            logging.error(f"點位 {point_id} 不存在")
            return False
        point = self.points[point_id]
        if order_id:
            for pos in point.open_positions:
                if pos.get('order_id') == order_id:
                    current_price = self.get_market_price('HK.MHI2505')
                    if current_price:
                        success, _, _, _, msg = self.close_order.execute(order_id, pos.get('quantity', 0), pos.get('direction', 'long'))
                        if success:
                            point.close_position(order_id, current_price)
                            point.logger.info(f"點位 {point_id} 平倉訂單 {order_id}")
                        return success
            point.logger.error(f"點位 {point_id} 未找到訂單 {order_id}")
            return False
        else:
            success = True
            for pos in point.open_positions[:]:
                current_price = self.get_market_price('HK.MHI2505')
                if current_price:
                    success &= self.close_order.execute(pos.get('order_id'), pos.get('quantity', 0), pos.get('direction', 'long'))[0]
                    if success:
                        point.close_position(pos.get('order_id'), current_price)
            return success

    def close_all(self):
        """平倉所有點位的持倉"""
        success = True
        for point_id in self.points:
            success &= self.close_position(point_id)
        return success

    def get_status(self):
        """返回所有點位狀態"""
        return {point_id: point.get_status() for point_id, point in self.points.items()}