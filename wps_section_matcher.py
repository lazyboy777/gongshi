import re
import time
import pandas as pd

# ========= 配置：请根据实际表格名称修改 =========

SHEET_INPUT = "导出的待匹配工时内容"         # 待匹配工单所在的工作表（请修改为实际名称）
SHEET_STD   = "工时参考标准文件" # 标准工时库工作表
SHEET_OUTPUT_MATCHED = "匹配结果"   # 匹配成功结果的工作表
SHEET_OUTPUT_UNMATCHED = "未匹配结果"   # 未匹配/未完成结果的工作表

# ========= 辅助函数 =========

def normalize_reference_code(raw):
    """
    清洗参考编号/控制号/工卡号
    """
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    text = text.upper()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    # 去除 REV 及后续内容
    text = re.sub(r"\s+REV[^\s]*.*$", "", text)
    
    # 尝试提取字母前缀和数字
    m = re.match(r"([A-Z]+)\s*(.*)", text)
    if not m:
        # 如果没有字母前缀，只保留字母数字
        return re.sub(r"\W", "", text)
    
    prefix = m.group(1)
    rest = m.group(2)
    digits = re.findall(r"\d+", rest)
    if not digits:
        return prefix
    return prefix + "".join(digits)

def extract_section(status_raw):
    """
    从完成情况中提取工段信息
    """
    if status_raw is None:
        return "未完成"
    s = str(status_raw).strip()
    
    # 定义所有合法的工段关键词
    valid_keywords = [
        "一工段", "二工段", "三工段", "四工段",
        "排故一组", "排故二组", "客舱一组", "客舱二组"
    ]
    
    # 遍历匹配
    for kw in valid_keywords:
        if kw in s:
            return kw
            
    # 如果包含其他未定义的工段名，或者完全不匹配，则返回前20个字符以便查看，或直接标记未完成
    # 根据用户意图，只要不在上述列表里，就是未完成/未匹配
    return s[:20] if s else "未完成"

def _norm(s):
    """表头标准化辅助函数：转大写，去空格，去标点，去括号"""
    if s is None:
        return ""
    t = str(s)
    # 1. 替换全角空格和括号
    t = t.replace("\u00A0", " ").strip().upper()
    t = t.replace("（", " ").replace("）", " ").replace("(", " ").replace(")", " ")
    
    # 2. 替换换行符和标点
    t = t.replace("\n", " ").replace("\r", " ")
    t = t.replace("–", "").replace("—", "").replace("-", "")
    
    # 3. 去除所有空白字符
    t = re.sub(r"\s+", "", t)
    
    # 4. 去除其他非汉字、字母、数字的字符 (可选，但为了保留 'OR' 还是谨慎点，直接用 \w 即可)
    # t = re.sub(r"[^\w\u4E00-\u9FFF]", "", t) 
    
    return t

def deduplicate_columns(columns):
    """处理重复列名"""
    counts = {}
    new_columns = []
    for col in columns:
        col_str = str(col).strip() if col is not None else ""
        if not col_str:
            col_str = "Unnamed"
        if col_str in counts:
            counts[col_str] += 1
            new_columns.append(f"{col_str}.{counts[col_str]}")
        else:
            counts[col_str] = 0
            new_columns.append(col_str)
    return new_columns

def ensure_header(df):
    """
    确保第一行是正确的表头。
    扫描前 10 行，找到包含最多关键词（如‘控制号’、‘工卡号’、‘完成情况’）的行作为表头。
    """
    if df.empty:
        return df
    
    # 定义核心关键词（标准化后的）
    keys = {"控制号", "工卡号", "依据文件", "完成情况", "工时", "CONTROLNO", "STATUS"}
    
    def count_matches(row_values):
        row_norm = [_norm(v) for v in row_values]
        match_count = 0
        for val in row_norm:
            for k in keys:
                if k in val: 
                    match_count += 1
                    break
        return match_count

    # 1. 检查当前表头
    current_matches = count_matches(df.columns)
    best_idx = -1
    max_matches = current_matches
    
    # 2. 扫描前 50 行（或者更多，取决于用户粘贴的乱度）
    rows_to_scan = min(len(df), 50)
    for i in range(rows_to_scan):
        row_matches = count_matches(df.iloc[i].values)
        if row_matches > max_matches:
            max_matches = row_matches
            best_idx = i
            
    # 3. 如果找到更好的表头行，则进行提升
    if best_idx != -1:
        print(f"提示：在第 {best_idx + 1} 行（索引 {best_idx}）检测到有效表头，正在重新设置列名...")
        new_header = df.iloc[best_idx].values
        # 数据从 best_idx + 1 行开始
        df_new = df.iloc[best_idx+1:].copy()
        new_cols = [str(v) if v is not None else "" for v in new_header]
        df_new.columns = deduplicate_columns(new_cols)
        return df_new
    
    # 如果没变，还是处理一下当前列名的重复问题
    df.columns = deduplicate_columns(df.columns)
    return df

def process_mixed_data(df):
    """
    高级数据处理函数：
    1. 自动扫描整个 DataFrame，寻找所有表头行。
    2. 将数据切分为多个块（Block）。
    3. 统一对齐列名并合并。
    4. 返回合并后的 DataFrame 和 处理报告。
    """
    if df.empty:
        return df, "数据为空"
    
    # 1. 寻找“种子表头”（Primary Header）
    # 使用现有的关键词密度算法找到第一个最佳表头
    keys = {"控制号", "工卡号", "依据文件", "完成情况", "工时", "CONTROLNO", "STATUS", "机号", "机型", "序号"}
    
    def get_row_signature(row_values):
        """生成行的特征指纹（标准化后的集合）"""
        return {_norm(v) for v in row_values if v is not None and str(v).strip() != ""}

    def count_matches(row_values):
        row_norm = [_norm(v) for v in row_values]
        match_count = 0
        for val in row_norm:
            for k in keys:
                if k in val: 
                    match_count += 1
                    break
        return match_count

    # 扫描前 50 行找到第一个最佳表头
    best_idx = -1
    max_matches = count_matches(df.columns) # 先看看当前表头行
    
    # 如果当前表头已经是最佳，那它就是种子；否则在下面找
    rows_to_scan = min(len(df), 50)
    for i in range(rows_to_scan):
        row_matches = count_matches(df.iloc[i].values)
        if row_matches > max_matches:
            max_matches = row_matches
            best_idx = i
            
    # 确定种子表头的指纹
    if best_idx == -1:
        # 默认使用当前列名作为种子
        primary_signature = get_row_signature(df.columns)
        first_header_row_idx = -1 # -1 表示 df.columns
    else:
        primary_signature = get_row_signature(df.iloc[best_idx].values)
        first_header_row_idx = best_idx

    # 如果指纹太弱（比如只有1个词），可能不可靠，但还是试着往下走
    if len(primary_signature) == 0:
        print("警告：无法识别出明显的表头特征，将按普通表格处理。")
        return ensure_header(df), "未检测到有效表头，已按单表处理"

    print(f"识别到种子表头特征（包含 {len(primary_signature)} 个有效字段），开始全局扫描...")

    # 2. 全局扫描所有表头位置（使用向量化加速）
    print("正在加速扫描全局表头...")
    header_indices = set()
    
    # 将 DataFrame 转换为字符串（为了搜索），只取前 50 列以防太宽
    # 大多数情况下表头在前几列就能确定
    cols_to_scan = df.columns[:50]
    df_str = df[cols_to_scan].astype(str)
    
    # 核心关键词正则表达式
    # 只要行中包含这些词之一，就认为是候选表头
    keyword_regex = "控制号|工卡号|依据文件|完成情况|CONTROLNO|STATUS"
    
    # 对每一列进行搜索，找到包含关键词的行索引
    # 使用向量化操作比 iterrows 快得多
    candidate_mask = pd.Series(False, index=df.index)
    for col in df_str.columns:
        # case=False 忽略大小写, na=False 处理空值
        if df_str[col].dtype == 'object' or True: # 强制都查
             # 注意：这是查找该列中包含关键词的行
             mask = df_str[col].str.contains(keyword_regex, case=False, regex=True, na=False)
             candidate_mask = candidate_mask | mask

    # 获取候选行索引
    candidate_indices = df.index[candidate_mask].tolist()
    
    # 对候选行进行严格指纹验证（二次确认）
    # 这样只对极少数行进行复杂计算，速度极快
    for idx in candidate_indices:
        row_sig = get_row_signature(df.iloc[idx].values)
        if len(primary_signature) > 0:
            overlap = len(row_sig & primary_signature)
            similarity = overlap / len(primary_signature)
            if similarity > 0.5: # 降低一点阈值，防止漏掉
                header_indices.add(idx)
                
    # 别忘了检查第一行（columns）
    current_col_sig = get_row_signature(df.columns)
    if len(primary_signature) > 0:
         overlap = len(current_col_sig & primary_signature)
         similarity = overlap / len(primary_signature)
         if similarity > 0.5:
              header_indices.add(-1)
    
    # 确保 best_idx 也在
    if best_idx != -1 and best_idx not in header_indices:
        header_indices.add(best_idx)
    
    header_indices = sorted(list(header_indices))
    print(f"全局扫描完成，共检测到 {len(header_indices)} 处表头，行号: {header_indices}")

    # 3. 切分数据块并合并
    blocks = []
    skipped_blocks = []
    
    # 为了方便处理，添加一个结束标记
    boundaries = header_indices + [len(df)]
    
    for k in range(len(boundaries) - 1):
        start_row = boundaries[k]
        end_row = boundaries[k+1]
        
        # 提取表头
        if start_row == -1:
            cols = [str(c) for c in df.columns]
            # 数据从 0 到 end_row
            block_data = df.iloc[0:end_row].copy()
        else:
            cols = [str(v) if v is not None else "" for v in df.iloc[start_row].values]
            # 数据从 start_row + 1 到 end_row
            block_data = df.iloc[start_row+1 : end_row].copy()
            
        # 彻底清洗空行：删除全为空的行
        # 这是为了防止空行被误当做数据处理，提高后续效率
        block_data.dropna(how='all', inplace=True)
        
        # 清理列名
        clean_cols = deduplicate_columns(cols)
        
        # 如果数据块为空，跳过
        if block_data.empty:
            # 记录跳过信息（仅调试用，不一定打印出来）
            # skipped_blocks.append(f"行 {start_row}: 数据块为空")
            continue
            
        # 设置列名
        # 注意：如果 block_data 的列数比 cols 少（不太可能，都是来自同一个df），或者多
        if len(block_data.columns) != len(clean_cols):
             # 极端情况，对齐长度
             min_len = min(len(block_data.columns), len(clean_cols))
             block_data = block_data.iloc[:, :min_len]
             block_data.columns = clean_cols[:min_len]
        else:
            block_data.columns = clean_cols
            
        # 记录来源行号（方便追溯）
        block_data["_source_row_start"] = start_row + 1
        block_data["_source_row_end"] = end_row
        
        blocks.append(block_data)

    # 4. 合并
    if not blocks:
        return df, "未提取到任何有效数据块"
        
    final_df = pd.concat(blocks, ignore_index=True)
    
    # 生成报告
    report = f"加速扫描模式：检测到 {len(header_indices)} 个表头，合并了 {len(blocks)} 个有效数据块。\n"
    report += f"最终有效数据行数: {len(final_df)}。"
        
    return final_df, report

def is_header_row(row, control_col_name, status_col_name):
    """
    判断某一行是否是重复的表头行（多文件粘贴导致）
    """
    # 简单的判定：如果该行控制号列的值等于列名本身，或者包含“控制号”字样
    # 且完成情况列也类似，那么极有可能是重复表头
    c_val = _norm(row.get(control_col_name))
    s_val = _norm(row.get(status_col_name)) if status_col_name else ""
    
    # 检查是否包含关键词
    if "控制号" in c_val or "工卡号" in c_val or "CONTROL" in c_val:
        return True
    if "序号" in c_val and "机号" in _norm(row.get(df_input.columns[1] if len(df_input.columns)>1 else "")):
        return True
        
    return False

def locate_col(df, candidates):
    """在 DataFrame 中查找匹配候选列表的列名"""
    cand_norm = {_norm(c) for c in candidates}
    # 1. 精确匹配（标准化后）
    for col in df.columns:
        if _norm(col) in cand_norm:
            return col
    # 2. 包含匹配
    for col in df.columns:
        nc = _norm(col)
        for c in cand_norm:
            if c in nc: # 只要包含关键词即可
                return col
    return None

# ========= 主流程 =========

def main():
    start_time = time.time()
    print("脚本开始运行...")

    # 1. 读取数据
    print(f"读取工作表: {SHEET_INPUT} 和 {SHEET_STD} ...")
    try:
        df_input = xl(sheet_name=SHEET_INPUT)
    except Exception:
        print(f"错误：无法读取工作表 '{SHEET_INPUT}'。请确保工作表名称正确（可在脚本开头的 SHEET_INPUT 变量处修改）。")
        return

    try:
        df_std = xl(sheet_name=SHEET_STD)
    except Exception:
        print(f"错误：无法读取标准库工作表 '{SHEET_STD}'。请确保该表存在。")
        return

    # 2. 预处理表头
    # 使用新的 process_mixed_data 替代 ensure_header
    print("正在进行智能多块数据合并...")
    df_input, report = process_mixed_data(df_input)
    print("--- 合并报告 ---")
    print(report)
    print("----------------")
    
    df_std = ensure_header(df_std)

    # 3. 定位关键列
    # 输入表关键列
    col_control = locate_col(df_input, ["控制号", "工卡号", "控制号(or工卡号)", "ControlNo"])
    col_status = locate_col(df_input, ["完成情况", "状态", "Status"])
    
    # 标准库关键列
    col_std_ref = locate_col(df_std, ["依据文件", "依据", "文档编号", "AMM编码"])
    col_std_hours = locate_col(df_std, ["参考标准工时", "标准工时", "工时"])

    if not col_control:
        print("错误：在输入表中未找到‘控制号’或‘工卡号’列。")
        print(f"当前列名: {df_input.columns.tolist()}")
        return
    if not col_status:
        print("警告：在输入表中未找到‘完成情况’列，将默认为‘未完成’。")
    
    if not col_std_ref or not col_std_hours:
        print("错误：在标准库表中未找到‘依据文件’或‘参考标准工时’列。")
        return

    print(f"定位列成功：\n控制号列='{col_control}'\n完成情况列='{col_status}'\n依据文件列='{col_std_ref}'\n标准工时列='{col_std_hours}'")

    # 4. 构建标准库索引
    print("构建标准工时索引...")
    std_index = {} # 清洗后的编码 -> 工时
    # 注意：如果同一编码对应多个工时，这里会覆盖，取最后一个。根据需求通常是唯一的。
    count_std = 0
    for _, row in df_std.iterrows():
        ref = row.get(col_std_ref)
        hours = row.get(col_std_hours)
        if pd.isna(hours): 
            continue
            
        norm_ref = normalize_reference_code(ref)
        if norm_ref:
            std_index[norm_ref] = hours
            count_std += 1
            
    print(f"标准库索引构建完成，有效条目数: {count_std}")

    # 5. 遍历匹配
    print("开始匹配工单...")
    results_matched = []
    results_unmatched = []
    base_cols = list(df_input.columns)
    
    count_matched = 0
    count_unmatched = 0
    
    for idx, row in df_input.iterrows():
        # 跳过空行
        if row.isna().all():
            continue
            
        control_raw = row.get(col_control)
        
        # [已移除旧的手动跳过表头逻辑，process_mixed_data 已经处理了]
        
        status_raw = row.get(col_status) if col_status else None
        
        # 提取工段
        section = extract_section(status_raw)
        
        # 匹配工时
        norm_code = normalize_reference_code(control_raw)
        std_hours = std_index.get(norm_code)
        
        # 构造结果行
        res_item = row.to_dict()
        res_item["归属工段"] = section
        res_item["标准化控制号"] = norm_code
        res_item["匹配到的标准工时"] = std_hours
        
        # 判断是否匹配成功且完成
        is_success = False
        
        if std_hours is not None:
            res_item["匹配状态"] = "匹配成功"
            
            # 只有匹配成功 且 归属工段在合法列表中，才算真正的成功，进入统计表
            # 用户指定：一二三四工段、排故一二组、客舱一二组 都要匹配进入统计表
            # 其他情况（即使匹配到了工时，但工段不对）也算未匹配结果
            valid_sections = [
                "一工段", "二工段", "三工段", "四工段",
                "排故一组", "排故二组", "客舱一组", "客舱二组"
            ]
            
            if section in valid_sections:
                is_success = True
            else:
                is_success = False # 工段不在指定列表中，强制归入未匹配结果
        else:
            if not norm_code:
                res_item["匹配状态"] = "控制号为空"
            else:
                res_item["匹配状态"] = "未匹配"
            is_success = False

        # 排序辅助值
        sort_map = {
            "一工段": 1,
            "二工段": 2,
            "三工段": 3,
            "四工段": 4,
            "排故一组": 5,
            "排故二组": 6,
            "客舱一组": 7,
            "客舱二组": 8
        }
        res_item["_sort_val"] = sort_map.get(section, 99)
            
        if is_success:
            results_matched.append(res_item)
            count_matched += 1
        else:
            results_unmatched.append(res_item)
            count_unmatched += 1

    if not results_matched and not results_unmatched:
        print("提示：没有处理任何数据行。")
        return

    # 6. 生成结果 DataFrame 并写入
    
    # === 预先清空目标工作表（防止残留旧数据） ===
    print(f"正在清空目标工作表: '{SHEET_OUTPUT_MATCHED}' 和 '{SHEET_OUTPUT_UNMATCHED}' ...")
    try:
        delete_xl("A1:ZZ100000", sheet_name=SHEET_OUTPUT_MATCHED)
    except Exception:
        pass # 可能表不存在，忽略
        
    try:
        delete_xl("A1:ZZ100000", sheet_name=SHEET_OUTPUT_UNMATCHED)
    except Exception:
        pass # 可能表不存在，忽略

    # === 处理匹配成功表 ===
    if results_matched:
        df_matched = pd.DataFrame(results_matched)
        df_matched = df_matched.sort_values(by=["_sort_val", col_control], ascending=[True, True])
        df_matched = df_matched.drop(columns=["_sort_val"])
        
        # 调整列顺序
        cols = df_matched.columns.tolist()
        priority_cols = ["归属工段", "匹配到的标准工时", "匹配状态", "标准化控制号"]
        other_cols = [c for c in cols if c not in priority_cols]
        df_matched = df_matched[priority_cols + other_cols]
        
        print(f"正在写入匹配成功结果到 '{SHEET_OUTPUT_MATCHED}' ({len(df_matched)} 行) ...")
        try:
            write_xl(df_matched, "A1", sheet_name=SHEET_OUTPUT_MATCHED)
        except Exception as e:
            if "not exist" in str(e):
                print(f"!!! 严重错误：工作表 '{SHEET_OUTPUT_MATCHED}' 不存在。")
                print(f"请在 WPS 底部点击 '+' 号，手动新建一个名为 '{SHEET_OUTPUT_MATCHED}' 的工作表，然后再次运行脚本。")
            else:
                raise e
    else:
        print(f"提示：没有匹配成功的数据，工作表 '{SHEET_OUTPUT_MATCHED}' 将为空。")

    # === 处理未匹配/未完成表 ===
    if results_unmatched:
        df_unmatched = pd.DataFrame(results_unmatched)
        # 未匹配也可以按工段排序，或者直接按控制号
        df_unmatched = df_unmatched.sort_values(by=["_sort_val", col_control], ascending=[True, True])
        df_unmatched = df_unmatched.drop(columns=["_sort_val"])
        
        cols = df_unmatched.columns.tolist()
        priority_cols = ["归属工段", "匹配到的标准工时", "匹配状态", "标准化控制号"]
        other_cols = [c for c in cols if c not in priority_cols]
        df_unmatched = df_unmatched[priority_cols + other_cols]
        
        print(f"正在写入未匹配/未完成结果到 '{SHEET_OUTPUT_UNMATCHED}' ({len(df_unmatched)} 行) ...")
        try:
            write_xl(df_unmatched, "A1", sheet_name=SHEET_OUTPUT_UNMATCHED)
        except Exception as e:
            if "not exist" in str(e):
                print(f"!!! 严重错误：工作表 '{SHEET_OUTPUT_UNMATCHED}' 不存在。")
                print(f"请在 WPS 底部点击 '+' 号，手动新建一个名为 '{SHEET_OUTPUT_UNMATCHED}' 的工作表，然后再次运行脚本。")
            else:
                raise e
    else:
        print(f"提示：没有未匹配的数据，工作表 '{SHEET_OUTPUT_UNMATCHED}' 将为空。")
    
    elapsed = time.time() - start_time
    print(f"处理完成！总耗时 {elapsed:.2f} 秒。")
    print(f"统计：成功匹配且已完成 {count_matched} 行，未匹配或未完成 {count_unmatched} 行。")


# 运行主函数
main()
