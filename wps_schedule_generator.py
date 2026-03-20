"""
排班表生成器
功能：从航班信息表生成排班表，识别航前/短停/航后
作者：WPS Python 脚本
创建时间：2026-03-17
版本：1.5 (排序后筛选，对每条记录判断机型)
"""

import pandas as pd

# ========= 配置 =========
SHEET_FLIGHT = "航班信息"      # 航班信息表名称
SHEET_SCHEDULE = "排班表"      # 排班表输出名称
BASE_AIRPORT = "北京大兴"      # 航前判断的基地机场

# 筛选条件 1：预筛选（在生成排班表前执行）
# 只保留这些机型系列的航班（320、330、350 系列）
PRE_FILTER_PREFIXES = [
    "320", "322", "32A", "32B", "32C", "32D", "32E", "32G", 
    "32N", "32V", "3HX", "321", "324", "327", "328", "329", 
    "32J", "32H", "32K", "32L", "32M", "32Q", "32R", "32X", 
    "32Y", "32Z", # 320 系列
    "333", "33C", "33G", "33H", "33W",           # 330 系列
    "350", "359"                                 # 350 系列
]

# 筛选条件 2：业务规则筛选（在生成排班表后执行）
# 如果**这条排班记录**的机型以这些前缀开头 (主要针对 320 系列)，
# 则这条记录必须满足：出发站在列表 AND 到达站是北京大兴才保留
FILTER_MODEL_PREFIXES = [
    "320", "322", "32A", "32B", "32C", "32D", "32E", "32G", 
    "32N", "32V", "3HX", "321", "324", "327", "328", "329", 
    "32J", "32H", "32K", "32L", "32M", "32Q", "32R", "32X", 
    "32Y", "32Z"
]
# 需要筛选时，只保留这些出发站
FILTER_ALLOWED_DEPATURE = ["大连", "长春", "长沙黄花", "哈尔滨"]
# 需要筛选时，只保留到达站是北京大兴
FILTER_ALLOWED_ARRIVE = ["北京大兴"]


def main():
    print("排班表生成器启动...")
    
    # 1. 读取航班信息
    print(f"读取工作表: {SHEET_FLIGHT}")
    try:
        df_flight = xl(sheet_name=SHEET_FLIGHT)
    except Exception as e:
        print(f"错误：读取工作表 '{SHEET_FLIGHT}' 失败: {e}")
        return
    
    if df_flight.empty:
        print("错误：航班信息表为空")
        return
    
    print(f"读取完成，共 {len(df_flight)} 行数据")
    
    # 【新增步骤】提前进行机型筛选：仅保留 320、330、350 系列
    model_col_idx = 4 # 第5列是机型
    total_raw = len(df_flight)
    # 核心修复：确保将机型列转换为字符串并去除空格，防止 350/359 被识别为数字而导致 startswith 失败
    df_flight = df_flight[df_flight.iloc[:, model_col_idx].astype(str).str.strip().str.startswith(tuple(PRE_FILTER_PREFIXES), na=False)]
    print(f"预筛选完成：原数据 {total_raw} 条，保留 320/330/350 系列后剩余 {len(df_flight)} 条")
    
    if df_flight.empty:
        print("预筛选后没有符合机型的航班数据")
        return
    
    # 2. 预处理：按飞机号排序（D列第4列）
    plane_col = df_flight.columns[3]
    df_flight = df_flight.sort_values(by=plane_col, ascending=True)
    
    # 3. 初始化结果
    results = []
    i = 0  # 行索引
    row_count = len(df_flight)
    
    # 遍历每架飞机的航班
    while i < row_count:
        current_plane = df_flight.iloc[i, 3]
        # 收集同一飞机的所有航班
        group_rows = []
        while i < row_count and df_flight.iloc[i, 3] == current_plane:
            group_rows.append(df_flight.iloc[i].to_dict())
            i += 1
        
        # 如果分组为空，继续
        if not group_rows:
            continue
        
        # 按进港时间排序（H列第8列）
        group_rows.sort(key=lambda x: str(x.get(df_flight.columns[7], "")))
        
        m = len(group_rows)
        n = 0
        
        # 处理每条航班
        while n < m:
            current = group_rows[n]
            col6 = current.get(df_flight.columns[5], "")  # 第6列出发站
            
            if str(col6).strip() == BASE_AIRPORT:
                # 航前
                results.append({
                    "序号": "",
                    "性质": current.get(df_flight.columns[1], ""),
                    "航班性质": "航前",
                    "飞机号": current.get(df_flight.columns[3], ""),
                    "机型": current.get(df_flight.columns[4], ""),
                    "进港航班": "——",
                    "进港时间": "——",
                    "出港航班": current.get(df_flight.columns[2], ""),
                    "出港时间": current.get(df_flight.columns[7], ""),
                    "出发站": current.get(df_flight.columns[5], ""),
                    "到达站": current.get(df_flight.columns[16], ""),
                    "下一站": "——",
                    "飞机所属": current.get(df_flight.columns[21], ""),
                    "_order": 1,
                    "_sort": 1,
                })
                n += 1
            elif n + 1 >= m or pd.isna(group_rows[n + 1].get(df_flight.columns[5])):
                # 航后
                results.append({
                    "序号": "",
                    "性质": current.get(df_flight.columns[1], ""),
                    "航班性质": "航后",
                    "飞机号": current.get(df_flight.columns[3], ""),
                    "机型": current.get(df_flight.columns[4], ""),
                    "进港航班": current.get(df_flight.columns[2], ""),
                    "进港时间": current.get(df_flight.columns[18], ""),
                    "出港航班": "——",
                    "出港时间": "——",
                    "出发站": current.get(df_flight.columns[5], ""),
                    "到达站": current.get(df_flight.columns[16], ""),
                    "下一站": "——",
                    "飞机所属": current.get(df_flight.columns[21], ""),
                    "_order": 3,
                    "_sort": current.get(df_flight.columns[18], ""),
                })
                n += 1
            else:
                # 短停
                next_row = group_rows[n + 1]
                results.append({
                    "序号": "",
                    "性质": current.get(df_flight.columns[1], ""),
                    "航班性质": "短停",
                    "飞机号": current.get(df_flight.columns[3], ""),
                    "机型": current.get(df_flight.columns[4], ""),
                    "进港航班": current.get(df_flight.columns[2], ""),
                    "进港时间": current.get(df_flight.columns[18], ""),
                    "出港航班": next_row.get(df_flight.columns[2], ""),
                    "出港时间": next_row.get(df_flight.columns[7], ""),
                    "出发站": current.get(df_flight.columns[5], ""),
                    "到达站": current.get(df_flight.columns[16], ""),
                    "下一站": next_row.get(df_flight.columns[16], ""),
                    "飞机所属": current.get(df_flight.columns[21], ""),
                    "_order": 2,
                    "_sort": current.get(df_flight.columns[18], ""),
                })
                n += 2
    
    print(f"生成 {len(results)} 条排班记录")
    
    if not results:
        print("未生成任何排班记录")
        return
    
    # 4. 排序：按航班性质→时间
    df_result = pd.DataFrame(results)
    df_result = df_result.sort_values(by=["_order", "_sort"], ascending=[True, True])
    
    # 添加序号
    cnt_pre = cnt_short = cnt_after = 0
    for idx, row in df_result.iterrows():
        if row["航班性质"] == "航前":
            cnt_pre += 1
            df_result.loc[idx, "序号"] = cnt_pre
        elif row["航班性质"] == "短停":
            cnt_short += 1
            df_result.loc[idx, "序号"] = cnt_short
        else:
            cnt_after += 1
            df_result.loc[idx, "序号"] = cnt_after
    
    # ===== 排序添加序号之后，在这里进行筛选 =====
    print("开始筛选...")
    total_before = len(df_result)
    filtered_count = 0
    
    def keep_record(row):
        nonlocal filtered_count
        model = str(row["机型"]) if pd.notna(row["机型"]) else ""
        # 判断这条记录的机型是否需要筛选
        need_filter = False
        for prefix in FILTER_MODEL_PREFIXES:
            if model.startswith(prefix):
                need_filter = True
                break
        # 不需要筛选，保留
        if not need_filter:
            return True
        # 需要筛选，检查出发站和到达站
        depart = str(row["出发站"]).strip() if pd.notna(row["出发站"]) else ""
        arrive = str(row["到达站"]).strip() if pd.notna(row["到达站"]) else ""
        keep = depart in FILTER_ALLOWED_DEPATURE and arrive in FILTER_ALLOWED_ARRIVE
        if not keep:
            filtered_count += 1
        return keep
    
    df_result = df_result[df_result.apply(keep_record, axis=1)]
    
    print(f"筛选完成：共 {total_before} 条，筛除 {filtered_count} 条，剩余 {len(df_result)} 条")
    
    if df_result.empty:
        print("筛选后没有剩余记录")
        return
    
    # 删除辅助列
    df_result = df_result.drop(columns=["_order", "_sort"])
    
    # 调整列顺序
    cols = ["序号", "飞机所属", "性质", "航班性质", "飞机号", "机型", "进港航班", "进港时间", 
            "出港航班", "出港时间", "出发站", "到达站", "下一站" ]
    df_result = df_result[cols]
    
    # 5. 写入排班表
    print(f"清空并写入 {SHEET_SCHEDULE}")
    try:
        delete_xl("A1:ZZ100000", sheet_name=SHEET_SCHEDULE)
    except:
        pass
    
    write_xl(df_result, "A1", sheet_name=SHEET_SCHEDULE)
    
    # 重新统计
    cnt_pre = len(df_result[df_result["航班性质"] == "航前"])
    cnt_short = len(df_result[df_result["航班性质"] == "短停"])
    cnt_after = len(df_result[df_result["航班性质"] == "航后"])
    
    print(f"\n生成完成！")
    print(f"  最终总记录: {len(df_result)}")
    print(f"  航前: {cnt_pre}")
    print(f"  短停: {cnt_short}")
    print(f"  航后: {cnt_after}")
    print(f"  业务筛选掉 (320系列车站过滤): {filtered_count}")
    print(f"\n筛选逻辑说明：")
    print(f"  1. 预筛选：原始航班数据仅保留机型为 320/330/350 系列的记录")
    print(f"  2. 业务筛选：针对 320 系列，出发站必须在 {FILTER_ALLOWED_DEPATURE} 且 到达站必须是 {FILTER_ALLOWED_ARRIVE}")
    print(f"  3. 其他机型 (330/350)：直接保留")


# 运行主函数
if __name__ == "__main__":
    main()