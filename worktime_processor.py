import re
import time
from typing import Any, Dict, List, Tuple, Optional

import pandas as pd

# ========= 配置：根据你文档里的 Sheet 名和列名调整 =========

SHEET_ORDERS = "导出的待匹配工时内容"   # 工单所在工作表
SHEET_STD    = "工时参考标准文件"   # 标准工时库工作表
SHEET_MATCH  = "匹配结果"   # 匹配结果表
SHEET_UNMATCH = "未匹配结果"  # 未匹配结果表
SHEET_SECTIONS = "工段分布"  # 工段分布表

COL_MODEL      = "机型"
COL_REF_DOC    = "依据文件"
COL_STD_HOURS  = "参考标准工时"

FUZZY_PREFIX_LEN = 6


def normalize_model(model_raw: Any) -> str:
    if model_raw is None or (isinstance(model_raw, float) and pd.isna(model_raw)):
        return ""
    s = str(model_raw).strip().upper()
    if s in ("A320", "A321", "A319"):
        return "A320S"
    return s


def build_section_mapping(df_sections: pd.DataFrame) -> Dict[str, str]:
    """
    解析工段分布表，返回 员工号 -> 工段名称 的映射字典。
    采用全表扫描模式，自动定位“员工号”所在行，并取其上一行作为工段名称。
    """
    if df_sections.empty:
        return {}
    
    # 将 DataFrame 转换为二维列表（包含表头）
    # 注意：xl() 默认第一行为 columns，后续为 values
    data = [df_sections.columns.tolist()] + df_sections.values.tolist()
    
    # 1. 寻找“员工号”所在的行索引
    header_row_idx = -1
    for r, row in enumerate(data[:10]):  # 仅扫描前10行
        if any("员工号" in str(cell).strip() for cell in row):
            header_row_idx = r
            break
            
    if header_row_idx == -1:
        print("警告：在工段分布表中未找到“员工号”列，无法建立映射。")
        return {}
        
    # 2. 确定工段名称所在行（默认为表头行的上一行）
    section_row_idx = header_row_idx - 1
    if section_row_idx < 0:
        print("警告：找到“员工号”列，但无法获取其上方的工段名称行。")
        return {}
        
    section_row = data[section_row_idx]
    header_row = data[header_row_idx]
    
    mapping = {}
    current_section = "未知工段"
    
    # 3. 遍历列，建立映射
    for c in range(len(header_row)):
        # 更新当前工段（处理合并单元格逻辑）
        # 如果当前列有工段名，更新 current_section；如果是 NaN/Unnamed，保持沿用
        sec_val = str(section_row[c]).strip()
        if sec_val and "Unnamed" not in sec_val and sec_val.lower() != "nan":
            current_section = sec_val
            
        # 检查当前列是否为“员工号”
        head_val = str(header_row[c]).strip()
        if "员工号" in head_val:
            # 读取该列下方所有数据
            for r in range(header_row_idx + 1, len(data)):
                if c >= len(data[r]): # 防止越界
                    continue
                val = data[r][c]
                if pd.isna(val) or str(val).strip() == "":
                    continue
                # 格式清洗：去除 .0 和空格
                uid = str(val).strip().replace(".0", "")
                if uid:
                    mapping[uid] = current_section
                    
    return mapping


# ========= 编码清洗 =========

def normalize_reference_code(raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw).strip()
    if not text:
        return ""
    text = text.upper()
    text = text.replace("–", "-").replace("—", "-")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+REV[^\s]*.*$", "", text)
    m = re.match(r"([A-Z]+)\s*(.*)", text)
    if not m:
        return re.sub(r"\W", "", text)
    prefix = m.group(1)
    rest = m.group(2)
    digits = re.findall(r"\d+", rest)
    if not digits:
        return prefix
    return prefix + "".join(digits)


# ========= 构建标准库索引 =========

def build_std_index(df_std: pd.DataFrame) -> Tuple[
    Dict[Tuple[str, str], Dict[str, Any]],
    Dict[Tuple[str, str], List[Dict[str, Any]]]
]:
    index_exact: Dict[Tuple[str, str], Dict[str, Any]] = {}
    index_prefix: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for _, row in df_std.iterrows():
        model = normalize_model(row.get(COL_MODEL))
        ref_raw = row.get(COL_REF_DOC)
        if not model and (ref_raw is None or (isinstance(ref_raw, float) and pd.isna(ref_raw))):
            continue
        norm_code = normalize_reference_code(ref_raw)
        if not model or not norm_code:
            continue
        std_hours = row.get(COL_STD_HOURS)
        data = {
            "model": model,
            "norm_code": norm_code,
            "std_hours": std_hours
        }
        key = (model, norm_code)
        if key not in index_exact:
            index_exact[key] = data
        prefix = norm_code[:FUZZY_PREFIX_LEN] if len(norm_code) >= FUZZY_PREFIX_LEN else norm_code
        pkey = (model, prefix)
        index_prefix.setdefault(pkey, []).append(data)
    return index_exact, index_prefix


def common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def match_single(
    index_exact: Dict[Tuple[str, str], Dict[str, Any]],
    index_prefix: Dict[Tuple[str, str], List[Dict[str, Any]]],
    model_raw: Any,
    ref_raw: Any
) -> Tuple[str, str, Optional[Any], str]:
    model = normalize_model(model_raw)
    if not model:
        return "", "未匹配", None, "机型为空，无法匹配"
    norm_code = normalize_reference_code(ref_raw)
    if not norm_code:
        return "", "未匹配", None, "依据文件为空或格式无法识别，无法匹配"
    key = (model, norm_code)
    if key in index_exact:
        std_hours = index_exact[key]["std_hours"]
        return norm_code, "完全匹配", std_hours, "根据机型和标准化编码完全匹配到标准工时"
    prefix = norm_code[:FUZZY_PREFIX_LEN] if len(norm_code) >= FUZZY_PREFIX_LEN else norm_code
    pkey = (model, prefix)
    candidates = index_prefix.get(pkey, [])
    if candidates:
        best = max(candidates, key=lambda c: common_prefix_len(norm_code, c["norm_code"]))
        std_hours = best["std_hours"]
        return norm_code, "近似匹配", std_hours, f"根据机型和编码前缀近似匹配到标准工时，库编码为 {best['norm_code']}"
    return norm_code, "未匹配", None, "在标准工时库中未找到对应记录"


def _norm(s: Any) -> str:
    if s is None:
        return ""
    t = str(s)
    t = t.replace("\u00A0", " ").strip().upper()
    t = t.replace("（", "(").replace("）", ")")
    t = t.replace("–", "-").replace("—", "-")
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[^\w\u4E00-\u9FFF]", "", t)
    return t


def deduplicate_columns(columns: List[Any]) -> List[str]:
    counts: Dict[str, int] = {}
    new_columns: List[str] = []
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


def ensure_header(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols_norm = [_norm(c) for c in df.columns]
    first = df.iloc[0]
    first_norm = [_norm(v) for v in first.values]
    keys = {_norm("机型"), _norm("依据文件"), _norm("参考标准工时")}
    if len(set(first_norm) & keys) >= 2 and len(set(cols_norm) & keys) == 0:
        df2 = df.iloc[1:].copy()
        new_cols = [str(v) if v is not None else "" for v in first.values]
        df2.columns = deduplicate_columns(new_cols)
        return df2
    
    # 确保原有列名也不重复
    df.columns = deduplicate_columns(df.columns)
    return df


def locate_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cand_norm = {_norm(c) for c in candidates}
    for col in df.columns:
        if _norm(col) in cand_norm:
            return col
    for col in df.columns:
        nc = _norm(col)
        for c in cand_norm:
            if nc.find(c) != -1 or c.find(nc) != -1:
                return col
    return None


# ========= 主流程：在当前文档中读 Sheet1/4，写 Sheet2/3 =========

start_time = time.time()
print("开始读取工作表数据……")

df_orders = xl(sheet_name=SHEET_ORDERS)
df_std = xl(sheet_name=SHEET_STD)
try:
    df_sections = xl(sheet_name=SHEET_SECTIONS)
except Exception:
    print(f"警告：未找到工作表 {SHEET_SECTIONS}，将无法匹配工段信息。")
    df_sections = pd.DataFrame()

df_orders = ensure_header(df_orders)
df_std = ensure_header(df_std)

orders_model_col = locate_col(df_orders, ["机型", "飞机型号", "机型号", "机型/机号", "飞机机型"])
orders_ref_col = locate_col(df_orders, ["依据文件", "依据", "文档编号", "AMM编码", "依据文件编码"])
orders_ac_col = locate_col(df_orders, ["飞机号", "机号", "注册号", "飞机注册号"])
orders_desc_col = locate_col(df_orders, ["故障描述（中文）", "故障描述", "中文故障描述"])
orders_status_col = locate_col(df_orders, ["工卡状态", "状态"])
orders_emp_id_col = locate_col(df_orders, ["关卡人工号", "人工号", "员工号"])
orders_emp_name_col = locate_col(df_orders, ["关卡人名称", "关卡人", "名称"])

std_model_col = locate_col(df_std, ["机型", "飞机型号", "机型号", "机型/机号", "飞机机型"])
std_ref_col = locate_col(df_std, ["依据文件", "依据", "文档编号", "AMM编码", "依据文件编码"])
std_hours_col = locate_col(df_std, ["参考标准工时", "标准工时", "工时标准", "参考工时", "工时"])

if not orders_model_col or not orders_ref_col:
    raise RuntimeError(f"工单表 {SHEET_ORDERS} 中未找到必需列，请检查表头是否包含 机型 和 依据文件")
if not std_model_col or not std_ref_col or not std_hours_col:
    raise RuntimeError(f"标准库表 {SHEET_STD} 中未找到必需列，请检查表头是否包含 机型、依据文件、参考标准工时")

COL_MODEL = orders_model_col
COL_REF_DOC = orders_ref_col
COL_STD_HOURS = std_hours_col

print("开始构建标准工时索引……")
index_exact, index_prefix = build_std_index(df_std)

print("开始构建工段映射……")
section_map = build_section_mapping(df_sections)

base_cols = list(df_orders.columns)

match_rows: List[List[Any]] = []
unmatch_rows: List[List[Any]] = []
unmatched_reason_counter: Dict[str, int] = {}

total_rows = len(df_orders)
print(f"开始匹配，共 {total_rows} 行工单……")

for idx, (_, row) in enumerate(df_orders.iterrows(), start=1):
    if row.isna().all() or all(
        (isinstance(v, str) and not v.strip()) or pd.isna(v)
        for v in row.values
    ):
        continue
    model_raw = row.get(orders_model_col)
    ref_raw = row.get(orders_ref_col)

    # 增强过滤：如果机型和依据文件均为空（或只包含空白字符），视为无效行直接跳过
    is_model_empty = model_raw is None or (isinstance(model_raw, float) and pd.isna(model_raw)) or str(model_raw).strip() == ""
    is_ref_empty = ref_raw is None or (isinstance(ref_raw, float) and pd.isna(ref_raw)) or str(ref_raw).strip() == ""
    
    if is_model_empty and is_ref_empty:
        continue
    
    # 获取员工信息及工段
    emp_id = row.get(orders_emp_id_col) if orders_emp_id_col else None
    emp_name = row.get(orders_emp_name_col) if orders_emp_name_col else None
    emp_id_str = str(emp_id).strip().replace(".0", "") if emp_id is not None else ""
    section = section_map.get(emp_id_str, "未匹配工段")
    
    # 检查工卡状态
    card_status = row.get(orders_status_col) if orders_status_col else None
    status_str = str(card_status).strip() if card_status else ""
    
    if status_str in ("已保留", "未完成"):
        norm_code = normalize_reference_code(ref_raw)
        reason = f"工卡状态为{status_str}"
        base_vals = [row.get(col) for col in base_cols]
        # 修改：未匹配原因放第一列
        unmatch_rows.append([reason] + base_vals + [norm_code, "未匹配", "黄色"])
        unmatched_reason_counter[reason] = unmatched_reason_counter.get(reason, 0) + 1
        continue
        
    try:
        norm_code, match_type, std_hours, desc = match_single(index_exact, index_prefix, model_raw, ref_raw)
        base_vals = [row.get(col) for col in base_cols]
        # 核心字段重组：所在工段(首列) + 机型 + 飞机号 + 依据文件 + 故障描述 + 关卡人工号 + 关卡人名称
        core_vals = [
            section,
            row.get(orders_model_col),
            row.get(orders_ac_col) if orders_ac_col else None,
            row.get(orders_ref_col),
            row.get(orders_desc_col) if orders_desc_col else None,
            emp_id,
            emp_name
        ]
        if match_type in ("完全匹配", "近似匹配"):
            match_rows.append(core_vals + [norm_code, match_type, "匹配成功", std_hours, desc])
        else:
            reason = desc
            # 修改：未匹配原因放第一列
            unmatch_rows.append([reason] + base_vals + [norm_code, "未匹配", "红色"])
            unmatched_reason_counter[reason] = unmatched_reason_counter.get(reason, 0) + 1
    except Exception:
        norm_code = normalize_reference_code(ref_raw)
        reason = "处理该行数据时发生异常，请检查数据格式"
        base_vals = [row.get(col) for col in base_cols]
        # 修改：未匹配原因放第一列
        unmatch_rows.append([reason] + base_vals + [norm_code, "未匹配", "红色"])
        unmatched_reason_counter[reason] = unmatched_reason_counter.get(reason, 0) + 1

    if idx % 500 == 0 or idx == total_rows:
        elapsed = time.time() - start_time
        print(f"已处理 {idx}/{total_rows} 行，用时 {elapsed:.1f} 秒")

# 生成 DataFrame
match_headers = [
    "所在工段",
    "机型",
    "飞机号",
    "依据文件",
    "故障描述（中文）",
    "关卡人工号",
    "关卡人名称",
    "标准化依据文件编码",
    "匹配类型",
    "匹配状态",
    "匹配到的标准工时",
    "匹配说明",
]
unmatch_headers = ["未匹配原因"] + base_cols + ["标准化依据文件编码", "匹配状态", "颜色标记"]

df_match = pd.DataFrame(match_rows, columns=match_headers)
df_unmatch = pd.DataFrame(unmatch_rows, columns=unmatch_headers)

if not df_unmatch.empty:
    # 按“未匹配原因”排序，确保相同原因的数据在一起，便于AirScript合并
    df_unmatch = df_unmatch.sort_values(by=["未匹配原因"], na_position='last')

if not df_match.empty:
    # 先按工段排序，确保相同工段的数据在一起，便于后续合并
    df_match = df_match.sort_values(by=["所在工段"], na_position='last')
    
    # 计算各工段汇总
    temp_hours = pd.to_numeric(df_match["匹配到的标准工时"], errors="coerce").fillna(0)
    unique_sections = df_match["所在工段"].dropna().unique()
    # 过滤空字符串和None
    unique_sections = [s for s in unique_sections if str(s).strip()]
    
    summary_rows_list = []
    # 按工段名称排序
    for section in sorted(unique_sections, key=lambda x: str(x)):
        # 筛选该工段的工时
        section_mask = df_match["所在工段"] == section
        section_total = temp_hours[section_mask].sum()
        
        row = {col: "" for col in match_headers}
        row["所在工段"] = f"{section}汇总工时"
        row["匹配到的标准工时"] = section_total
        summary_rows_list.append(row)

    if summary_rows_list:
        df_match = pd.concat([df_match, pd.DataFrame(summary_rows_list)], ignore_index=True)

# 在未匹配表底部追加原因统计
stats_rows = [{"未匹配原因": r, "数量": c} for r, c in unmatched_reason_counter.items()]
df_stats = pd.DataFrame(stats_rows, columns=["未匹配原因", "数量"]) if stats_rows else pd.DataFrame(columns=["未匹配原因", "数量"])

if not df_stats.empty:
    # 使用空字符串代替 None，避免 FutureWarning
    empty_row = {col: "" for col in df_unmatch.columns}
    df_unmatch = pd.concat([df_unmatch, pd.DataFrame([empty_row])], ignore_index=True)
    df_unmatch_stats = df_stats
else:
    df_unmatch_stats = pd.DataFrame(columns=["未匹配原因", "数量"])

# ========= 写回到 Sheet2 / Sheet3 =========

print("正在写入匹配结果到 匹配结果 / 未匹配结果……")

try:
    delete_xl("A1:ZZ100000", sheet_name=SHEET_MATCH)
except Exception:
    try:
        delete_xl("A:ZZ", sheet_name=SHEET_MATCH)
    except Exception:
        print(f"提示: 清空 {SHEET_MATCH} 时出现问题，已跳过清空步骤，将直接写入覆盖。")
try:
    delete_xl("A1:ZZ100000", sheet_name=SHEET_UNMATCH)
except Exception:
    try:
        delete_xl("A:ZZ", sheet_name=SHEET_UNMATCH)
    except Exception:
        print(f"提示: 清空 {SHEET_UNMATCH} 时出现问题，已跳过清空步骤，将直接写入覆盖。")

if not df_match.empty:
    write_xl(df_match, "A1", sheet_name=SHEET_MATCH)
else:
    write_xl(pd.DataFrame([{"提示": "没有任何匹配成功的记录"}]), "A1", sheet_name=SHEET_MATCH)

if not df_unmatch.empty:
    write_xl(df_unmatch, "A1", sheet_name=SHEET_UNMATCH)
    if not df_unmatch_stats.empty:
        start_row = len(df_unmatch) + 2
        write_xl(df_unmatch_stats, f"A{start_row}", sheet_name=SHEET_UNMATCH)
else:
    write_xl(pd.DataFrame([{"提示": "所有记录均匹配成功"}]), "A1", sheet_name=SHEET_UNMATCH)

elapsed_total = time.time() - start_time
print(f"全部处理完成，总耗时约 {elapsed_total:.1f} 秒。")
print(f"匹配成功 {len(df_match)-1} 行（含汇总行），未匹配 {len(df_unmatch)-1} 行（含空行）。")