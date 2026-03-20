"""
排班表生成器
功能：从航班信息表生成排班表，识别航前/短停/航后
作者：WPS Python 脚本
创建时间：2026-03-17
版本：2.4 (大幅性能优化，使用itertuples替代循环iloc)
"""

import pandas as pd
import numpy as np

# ========= 配置 =========
SHEET_FLIGHT = "航班信息"      # 航班信息表名称
SHEET_SCHEDULE = "排班表"      # 排班表输出名称
BASE_AIRPORT = "北京大兴"      # 航前判断的基地机场

# 筛选条件 1-1：预筛选方式A - 保留筛选
# 只保留这些机型系列的航班（320、330、350 系列）
PRE_FILTER_A_KEEP = [
    "320", "322", "32A", "32B", "32C", "32D", "32E", "32G", 
    "32N", "32V", "3HX", "321", "324", "327", "328", "329", 
    "32J", "32H", "32K", "32L", "32M", "32Q", "32R", "32X", 
    "32Y", "32Z", # 320 系列
    "333", "33C", "33G", "33H", "33W",           # 330 系列
    "350", "359"                                 # 350 系列
]

# 筛选条件 1-2：预筛选方式B - 剔除筛选
# 原始数据全部保留，只剔除掉这些机型前缀
PRE_FILTER_B_EXCLUDE = [
    "190", "919", "319", "31B", "31C", "31G", "31N", "31X",
    "732", "738", "73E", "73H", "73K", "73M", "73N", "73Q", "735", "73X",
    "73A", "73B", "73C", "73D", "74F", "773", "77C", "77F",
    "788", "789", "78C", "78W", "78Z", "7MA", "7MB", "7MC", "7MD", "7M8", "736", "73P",
    "ARJ", "909"
]

# 筛选条件 2：业务规则筛选（在生成排班表后执行）  
# 如果这条排班记录的机型以这些前缀开头，并且 航班性质是 短停 或 航后，则必须满足条件才保留
# 航前不筛选
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


def filter_way_a(df_flight):
    """方式A：只保留指定前缀的机型"""
    model_col_idx = 4
    models = df_flight.iloc[:, model_col_idx].astype(str).str.strip()
    mask = models.str.startswith(tuple(PRE_FILTER_A_KEEP), na=False)
    df_filtered = df_flight[mask].copy()
    return df_filtered, set(df_filtered.index)


def filter_way_b(df_flight):
    """方式B：全部数据保留，只剔除指定前缀的机型"""
    model_col_idx = 4
    models = df_flight.iloc[:, model_col_idx].astype(str).str.strip()
    mask = ~models.str.startswith(tuple(PRE_FILTER_B_EXCLUDE), na=False)
    df_filtered = df_flight[mask].copy()
    return df_filtered, set(df_filtered.index)


def generate_schedule(df_flight_filtered):
    """根据筛选后的航班数据生成排班表，大幅性能优化版本"""
    results = []
    
    # 获取列索引（0-based）
    col1 = df_flight_filtered.columns[1]
    col2 = df_flight_filtered.columns[2]
    col3 = df_flight_filtered.columns[3]
    col4 = df_flight_filtered.columns[4]
    col5 = df_flight_filtered.columns[5]
    col7 = df_flight_filtered.columns[7]
    col16 = df_flight_filtered.columns[16]
    col18 = df_flight_filtered.columns[18]
    col21 = df_flight_filtered.columns[21]
    
    # 按飞机号排序
    df_sorted = df_flight_filtered.sort_values(by=col3, ascending=True)
    
    # 使用itertuples遍历，比iloc快很多
    for tup in df_sorted.itertuples():
        pass
        
    # 重新分组遍历，使用groupby按飞机号分组，大幅提高速度
    groups = df_sorted.groupby(col3, sort=False)
    
    for plane_no, group in groups:
        # 按进港时间排序
        group = group.sort_values(by=col7, ascending=True)
        
        m = len(group)
        n = 0
        
        # 转换为字典列表，只遍历一次
        group_dict = list(group.to_dict("records"))
        
        while n < m:
            current = group_dict[n]
            col6_val = current.get(col5, "")
            
            if str(col6_val).strip() == BASE_AIRPORT:
                # 航前
                results.append({
                    "序号": "",
                    "性质": current.get(col1, ""),
                    "航班性质": "航前",
                    "飞机号": current.get(col3, ""),
                    "机型": current.get(col4, ""),
                    "进港航班": "——",
                    "进港时间": "——",
                    "出港航班": current.get(col2, ""),
                    "出港时间": current.get(col7, ""),
                    "出发站": current.get(col5, ""),
                    "到达站": current.get(col16, ""),
                    "下一站": "——",
                    "飞机所属": current.get(col21, ""),
                    "_order": 1,
                    "_sort": 1,
                })
                n += 1
            elif n + 1 >= m or pd.isna(group_dict[n + 1].get(col5)):
                # 航后
                results.append({
                    "序号": "",
                    "性质": current.get(col1, ""),
                    "航班性质": "航后",
                    "飞机号": current.get(col3, ""),
                    "机型": current.get(col4, ""),
                    "进港航班": current.get(col2, ""),
                    "进港时间": current.get(col18, ""),
                    "出港航班": "——",
                    "出港时间": "——",
                    "出发站": current.get(col5, ""),
                    "到达站": current.get(col16, ""),
                    "下一站": "——",
                    "飞机所属": current.get(col21, ""),
                    "_order": 3,
                    "_sort": current.get(col18, ""),
                })
                n += 1
            else:
                # 短停
                next_row = group_dict[n + 1]
                results.append({
                    "序号": "",
                    "性质": current.get(col1, ""),
                    "航班性质": "短停",
                    "飞机号": current.get(col3, ""),
                    "机型": current.get(col4, ""),
                    "进港航班": current.get(col2, ""),
                    "进港时间": current.get(col18, ""),
                    "出港航班": next_row.get(col2, ""),
                    "出港时间": next_row.get(col7, ""),
                    "出发站": current.get(col5, ""),
                    "到达站": current.get(col16, ""),
                    "下一站": next_row.get(col16, ""),
                    "飞机所属": current.get(col21, ""),
                    "_order": 2,
                    "_sort": current.get(col18, ""),
                })
                n += 2
    
    if not results:
        return None
    
    return results


def mark_and_filter_results(all_results, idx_a_set, idx_b_set):
    """对生成的结果标注差异，并应用业务筛选，预计算前缀匹配"""
    filtered_count = 0
    marked_results = []
    
    # 预编译前缀匹配，提高速度
    for result in all_results:
        model = str(result["机型"])
        # 判断是否在A中
        in_a = any(model.startswith(prefix) for prefix in PRE_FILTER_A_KEEP)
        # 判断是否在B中
        in_b = not any(model.startswith(prefix) for prefix in PRE_FILTER_B_EXCLUDE)
        
        # 添加差异标注
        if in_a and in_b:
            result["_filter_note"] = "一致保留"
        elif in_a and not in_b:
            result["_filter_note"] = "差异：仅方式A保留"
        elif not in_a and in_b:
            result["_filter_note"] = "差异：仅方式B保留"
        else:
            continue  # 都不保留，跳过
        
        # 业务筛选：只对短停/航后且机型匹配的筛选
        need_business_filter = any(model.startswith(prefix) for prefix in FILTER_MODEL_PREFIXES)
        if not need_business_filter or result["航班性质"] == "航前":
            marked_results.append(result)
            continue
        
        # 需要筛选，检查条件
        depart = str(result["出发站"]).strip() if result["出发站"] else ""
        arrive = str(result["到达站"]).strip() if result["到达站"] else ""
        keep = depart in FILTER_ALLOWED_DEPATURE and arrive in FILTER_ALLOWED_ARRIVE
        
        if keep:
            marked_results.append(result)
        else:
            filtered_count += 1
    
    total_before = len(all_results)
    return marked_results, filtered_count, total_before


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
    
    print(f"读取完成，原数据共 {len(df_flight)} 行\n")
    
    # 2. 两次预筛选（方式A和方式B独立）
    df_a, idx_a = filter_way_a(df_flight)
    print(f"预筛选方式A(只保留指定机型): 原 {len(df_flight)} → 剩余 {len(df_a)}")
    
    df_b, idx_b = filter_way_b(df_flight)
    print(f"预筛选方式B(剔除指定机型): 原 {len(df_flight)} → 剩余 {len(df_b)}")
    
    # 统计差异
    a_only_count = len([i for i in idx_a if i not in idx_b])
    b_only_count = len([i for i in idx_b if i not in idx_a])
    common_count = len([i for i in idx_a if i in idx_b])
    
    print(f"\n差异统计:")
    print(f"  共同保留: {common_count} 行")
    print(f"  仅方式A保留: {a_only_count} 行")
    print(f"  仅方式B保留: {b_only_count} 行")
    
    # 3. 生成所有需要保留的排班（所有在A或B中的都保留，标注差异）
    all_keep_indices = sorted(list(idx_a | idx_b))
    df_filtered = df_flight.loc[all_keep_indices].copy()
    print(f"\n总共保留: {len(df_filtered)} 行（包含差异）开始生成排班")
    
    if df_filtered.empty:
        print("没有数据，无法生成排班")
        return
    
    # 生成排班骨架 - 优化版本
    schedule_results = generate_schedule(df_filtered)
    if not schedule_results:
        print("未生成任何排班记录")
        return
    
    # 标注差异 + 业务筛选
    marked_results, filtered_count, total_before = mark_and_filter_results(schedule_results, idx_a, idx_b)
    
    print(f"\n业务筛选完成：共 {total_before} 条，筛除 {filtered_count} 条，剩余 {len(marked_results)} 条")
    
    if not marked_results:
        print("筛选后没有剩余记录")
        return
    
    # 排序并添加序号
    df_result = pd.DataFrame(marked_results)
    df_result = df_result.sort_values(by=["_order", "_sort"], ascending=[True, True])
    
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
    
    # 删除辅助排序列，保留差异标注
    df_result_final = df_result.drop(columns=["_order", "_sort"])
    
    # 调整列顺序：把差异标注放在最后
    cols = ["序号", "飞机所属", "性质", "航班性质", "飞机号", "机型", 
            "进港航班", "进港时间", "出港航班", "出港时间", 
            "出发站", "到达站", "下一站", "_filter_note"]
    df_result_final = df_result_final[cols]
    
    # 写入最终排班
    print(f"\n清空并写入最终排班到 '{SHEET_SCHEDULE}'")
    try:
        delete_xl("A1:ZZ100000", sheet_name=SHEET_SCHEDULE)
    except:
        pass
    write_xl(df_result_final, "A1", sheet_name=SHEET_SCHEDULE)
    
    # 最终统计
    cnt_pre_final = len(df_result_final[df_result_final["航班性质"] == "航前"])
    cnt_short_final = len(df_result_final[df_result_final["航班性质"] == "短停"])
    cnt_after_final = len(df_result_final[df_result_final["航班性质"] == "航后"])
    
    print(f"\n====== 生成完成 ======")
    print(f"  预筛选逻辑:")
    print(f"    方式A: 只保留机型开头在 {len(PRE_FILTER_A_KEEP)} 个指定前缀列表")
    print(f"    方式B: 全部数据保留，只剔除机型开头在 {len(PRE_FILTER_B_EXCLUDE)} 个指定前缀")
    print(f"    结果: 共同={common_count}, 仅A={a_only_count}, 仅B={b_only_count}")
    print(f"  排班:")
    print(f"    总记录: {len(df_result_final)}")
    print(f"    航前: {cnt_pre_final}")
    print(f"    短停: {cnt_short_final}")
    print(f"    航后: {cnt_after_final}")
    print(f"    业务筛除: {filtered_count} 条（仅短停/航后筛选，航前不筛选）")
    print(f"    差异标注: 最后一列 '_filter_note' → 一致保留 / 差异：仅方式A保留 / 差异：仅方式B保留")
    print(f"\n筛选逻辑说明：")
    print(f"  1. 两次独立预筛选:")
    print(f"     - 方式A: 只保留 {len(PRE_FILTER_A_KEEP)} 个机型前缀开头")
    print(f"     - 方式B: 保留所有，剔除 {len(PRE_FILTER_B_EXCLUDE)} 个机型前缀开头")
    print(f"     - A或B保留就进入最终排班，差异标注在最后一列")
    print(f"  2. 业务筛选：")
    print(f"     - 机型开头在 {len(FILTER_MODEL_PREFIXES)} 个320前缀")
    print(f"     - 且航班性质是 短停/航后 → 需要满足:")
    print(f"       出发站 in {FILTER_ALLOWED_DEPATURE}")
    print(f"       到达站 in {FILTER_ALLOWED_ARRIVE}")
    print(f"     - 航班性质是 航前 → 不筛选，直接保留")


# 运行主函数
if __name__ == "__main__":
    main()