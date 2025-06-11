import json
import os

# 讀取輸入 JSON 檔案
input_file = "HSI_json/HSI_Prediction_20250606.json"
with open(input_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 定義輸出根目錄
output_dir = "points"
os.makedirs(output_dir, exist_ok=True)

# 定義點位類型與 ID 映射
point_types = {
    "intraday_support": ["DS1", "DS2", "DS3"],
    "intraday_resistance": ["DP1", "DP2", "DP3"],
    "longterm_support": ["MLS1", "MLS2", "MLS3"],
    "longterm_resistance": ["MLP1", "MLP2", "MLP3"]
}

# 處理每個類型和點位
for point_type, point_ids in point_types.items():
    levels = data[point_type]["levels"]
    params_list = data[point_type]["params"]
    for i, (point_id, hit_price, params) in enumerate(zip(point_ids, levels, params_list)):
        orders = []
        tolerance = params["tolerance"]
        tp_fixed = params["tp_fixed"]
        qty_each_time = params["qty_each_time"]
        quantity_limits = params["quantity_limits"]
        # 計算開單數量：quantity_limits / qty_each_time
        num_trades = int(quantity_limits / qty_each_time)
        current_tolerance = tolerance

        for j in range(num_trades):
            if "support" in point_type:
                entry_price = hit_price - current_tolerance
                direction = "short"
                take_profit = hit_price - tp_fixed
                stop_loss = hit_price + tp_fixed
            else:
                entry_price = hit_price + current_tolerance
                direction = "long"
                take_profit = hit_price + tp_fixed
                stop_loss = hit_price - tp_fixed

            orders.append({
                "order_index": j,
                "entry_price": float(round(entry_price)),
                "direction": direction,
                "quantity": qty_each_time,
                "stop_loss": float(round(stop_loss)),
                "take_profit": float(round(take_profit))
            })

            # 每次減去一個 tolerance 後乘以 0.7
            current_tolerance *= 0.7

        point_config = {
            "point_id": point_id,
            "type": point_type.replace("_", " "),
            "hit_price": hit_price,
            "hit_limit": params["hit_limits"],
            "allow_hit": params["allow_hit"],
            "allow_entry": params["allow_entry"],
            "qty_each_time": qty_each_time,
            "quantity_limits": quantity_limits,
            "orders": orders
        }

        point_dir = os.path.join(output_dir, point_id)
        os.makedirs(point_dir, exist_ok=True)
        output_file = os.path.join(point_dir, f"{point_id}.json")
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump([point_config], f, indent=2, ensure_ascii=False)