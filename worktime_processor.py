"""
工时匹配处理器 - 根据机型和依据文件匹配标准工时
作者：自动生成
创建时间：2026-03-16
版本：v1.0
"""

import re
import time
import sys
import logging
from typing import Any, Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

SHEET_ORDERS = "导出的待匹配工时内容"
SHEET_STD    = "工时参考标准文件"
SHEET_MATCH  = "匹配结果"
SHEET_UNMATCH = "未匹配结果"
SHEET_SECTIONS = "工段分布"

COL_MODEL      = "机型"
COL_REF_DOC    = "依据文件"
COL_STD_HOURS  = "参考标准工时"

FUZZY_PREFIX_LEN = 6


def normalize_model(model_raw: Any) -> str:
    """标准化机型名称"""
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
    """标准化依据文件编码"""
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


# ========= 全向量化匹配逻辑 =========

def match_all_vectorized(df_orders: pd.DataFrame, df_std: pd.DataFrame, orders_status_col: Optional[str] = None) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    全向量化匹配工单与标准工时库
    
    Args:
        df_orders: 工单数据
        df_std: 标准工时库数据
        orders_status_col: 工单状态列名（可选）
    
    Returns:
        合并后的DataFrame和空行掩码
    """
    logger.info("开始进行全向量化匹配...")
    t_start = time.time()
    
    # 1. 预处理工单表
    # 保留原始索引以便最后排序（如果需要）
    df_orders = df_orders.copy()
    df_orders["_orig_idx"] = range(len(df_orders))
    
    # 向量化生成 key
    logger.info("正在计算工单匹配键...")
    df_orders["norm_model"] = df_orders[COL_MODEL].astype(str).map(normalize_model)
    df_orders["norm_code"] = df_orders[COL_REF_DOC].astype(str).map(normalize_reference_code)
    
    # 标记无效行
    # 机型为空 且 依据文件为空
    mask_empty = (df_orders["norm_model"] == "") & (df_orders["norm_code"] == "")
    
    # 2. 预处理标准库
    # 同样向量化生成 key
    logger.info("正在计算标准库匹配键...")
    df_std = df_std.copy()
    df_std["norm_model"] = df_std[COL_MODEL].astype(str).map(normalize_model)
    df_std["norm_code"] = df_std[COL_REF_DOC].astype(str).map(normalize_reference_code)
    
    # 过滤标准库无效行
    df_std_valid = df_std[
        (df_std["norm_model"] != "") & 
        (df_std["norm_code"] != "")
    ].copy()
    
    # 准备用于 merge 的标准库子集
    # 如果标准库有重复 (机型, 编码)，去重取第一个（或者按需处理）
    df_std_exact = df_std_valid.drop_duplicates(subset=["norm_model", "norm_code"])
    
    # 3. 第一轮：精确匹配 (Exact Match)
    logger.info("正在执行精确匹配...")
    # 左连接：工单 LEFT JOIN 标准库 ON (机型, 编码)
    df_merged = pd.merge(
        df_orders, 
        df_std_exact[["norm_model", "norm_code", COL_STD_HOURS]], 
        on=["norm_model", "norm_code"], 
        how="left",
        suffixes=("", "_std")
    )
    
    # 标记匹配成功的行
    df_merged["match_type"] = np.where(df_merged[COL_STD_HOURS].notna(), "完全匹配", "未匹配")
    df_merged["match_desc"] = np.where(
        df_merged[COL_STD_HOURS].notna(), 
        "根据机型和标准化编码完全匹配到标准工时", 
        ""
    )
    
    # 4. 第二轮：近似匹配 (Fuzzy Match) - 仅针对未匹配行
    # 这一步较难完全向量化，因为要找“最长前缀”。
    # 优化策略：
    #   a. 筛选出未匹配的工单
    #   b. 筛选出标准库中可能的候选集（构建前缀索引）
    #   c. 仅对这部分做循环，或者用更高级的 merge 技巧
    
    # 这里我们采用一种折中方案：
    # 依然构建前缀索引，但只对未匹配的行进行查找
    # 并且使用 apply 替代 iterrows
    
    mask_unmatched = df_merged["match_type"] == "未匹配"
    # 如果全匹配了，就跳过
    if mask_unmatched.any():
        logger.info(f"正在对 {mask_unmatched.sum()} 行未匹配数据进行近似匹配...")
        
        # 构建前缀索引 (只构建一次)
        # 结构: {(model, prefix): [candidate_code1, candidate_code2...]}
        # 为了加速，我们可以把标准库所有 code 及其 hours 存入字典
        # {(model, code): hours}
        std_dict = dict(zip(zip(df_std_valid["norm_model"], df_std_valid["norm_code"]), df_std_valid[COL_STD_HOURS]))
        
        # 构建前缀倒排索引: (model, prefix) -> list of full_codes
        prefix_map = {}
        for m, c in std_dict.keys():
            p = c[:FUZZY_PREFIX_LEN] if len(c) >= FUZZY_PREFIX_LEN else c
            if (m, p) not in prefix_map:
                prefix_map[(m, p)] = []
            prefix_map[(m, p)].append(c)
            
        def common_prefix_len(a: str, b: str) -> int:
            n = min(len(a), len(b))
            i = 0
            while i < n and a[i] == b[i]:
                i += 1
            return i
            
        def try_fuzzy_match(row):
            # 如果是空行或者已被标记为无效，跳过
            if row["norm_model"] == "" and row["norm_code"] == "":
                 return "未匹配", None, "无效行"
            
            m = row["norm_model"]
            c = row["norm_code"]
            
            # 状态检查
            status = str(row.get(orders_status_col, ""))
            if status in ("已保留", "未完成"):
                return "未匹配", None, f"工卡状态为{status}"
                
            p = c[:FUZZY_PREFIX_LEN] if len(c) >= FUZZY_PREFIX_LEN else c
            candidates = prefix_map.get((m, p), [])
            
            if not candidates:
                return "未匹配", None, "在标准工时库中未找到对应记录"
                
            # 找公共前缀最长的
            best_code = max(candidates, key=lambda x: common_prefix_len(c, x))
            hours = std_dict[(m, best_code)]
            return "近似匹配", hours, f"根据机型和编码前缀近似匹配到标准工时，库编码为 {best_code}"

        # 对未匹配行应用函数
        # apply 返回的是 Series，包含 (type, hours, desc)
        # 使用 result_type='expand' 拆分成多列
        fuzzy_results = df_merged.loc[mask_unmatched].apply(try_fuzzy_match, axis=1, result_type='expand')
        if not fuzzy_results.empty:
            fuzzy_results.columns = ["match_type", COL_STD_HOURS, "match_desc"]
            # 回填结果
            df_merged.loc[mask_unmatched, ["match_type", COL_STD_HOURS, "match_desc"]] = fuzzy_results

    logger.info(f"向量化匹配完成，总耗时 {time.time()-t_start:.2f} 秒")
    return df_merged, mask_empty


# ========= 结果拆分与格式化 =========

def split_and_format_results(df_merged: pd.DataFrame, mask_empty: pd.Series, section_map: Dict[str, str],
                              orders_ac_col: Optional[str] = None, orders_desc_col: Optional[str] = None,
                              orders_emp_id_col: Optional[str] = None, orders_emp_name_col: Optional[str] = None):
    """
    拆分并格式化匹配结果
    
    Args:
        df_merged: 合并后的数据
        mask_empty: 空行掩码
        section_map: 工段映射字典
        orders_ac_col: 飞机号列名
        orders_desc_col: 故障描述列名
        orders_emp_id_col: 员工号列名
        orders_emp_name_col: 员工名称列名
    
    Returns:
        匹配行、未匹配行和原因统计
    """
    logger.info("正在生成最终报表...")
    
    match_rows = []
    unmatch_rows = []
    reason_counter = {}
    
    # 预计算工段
    # 假设 emp_id 列存在
    if orders_emp_id_col:
        # 清洗工号
        emp_ids = df_merged[orders_emp_id_col].astype(str).str.strip().str.replace(".0", "", regex=False)
        # 映射工段
        sections = emp_ids.map(section_map).fillna("未匹配工段")
    else:
        sections = pd.Series(["未匹配工段"] * len(df_merged), index=df_merged.index)
        
    df_merged["_section"] = sections
    
    # 拆分 match / unmatch
    # 成功条件：match_type 为 完全匹配 或 近似匹配
    mask_success = df_merged["match_type"].isin(["完全匹配", "近似匹配"])
    
    # 1. 成功的数据
    df_success = df_merged[mask_success].copy()
    if not df_success.empty:
        # 构造输出列
        # "所在工段", "机型", "飞机号", "依据文件", "故障描述（中文）", "关卡人工号", "关卡人名称", "标准化依据文件编码", "匹配类型", "匹配状态", "匹配到的标准工时", "匹配说明"
        
        # 提取需要的列，如果不存在则填空
        res = pd.DataFrame()
        res["所在工段"] = df_success["_section"]
        res["机型"] = df_success[COL_MODEL]
        res["飞机号"] = df_success[orders_ac_col] if orders_ac_col else ""
        res["依据文件"] = df_success[COL_REF_DOC]
        res["故障描述（中文）"] = df_success[orders_desc_col] if orders_desc_col else ""
        res["关卡人工号"] = df_success[orders_emp_id_col] if orders_emp_id_col else ""
        res["关卡人名称"] = df_success[orders_emp_name_col] if orders_emp_name_col else ""
        res["标准化依据文件编码"] = df_success["norm_code"]
        res["匹配类型"] = df_success["match_type"]
        res["匹配状态"] = "匹配成功"
        res["匹配到的标准工时"] = df_success[COL_STD_HOURS]
        res["匹配说明"] = df_success["match_desc"]
        
        match_rows = res.values.tolist()
        
    # 2. 失败的数据 (排除无效空行)
    # mask_empty 是之前标记的 "机型和依据文件都为空" 的行，直接丢弃，不算未匹配
    mask_fail = (~mask_success) & (~mask_empty)
    df_fail = df_merged[mask_fail].copy()
    
    if not df_fail.empty:
        # "未匹配原因", 原始列..., "标准化依据文件编码", "匹配状态", "颜色标记"
        # 统计原因
        for reason in df_fail["match_desc"]:
             reason_counter[reason] = reason_counter.get(reason, 0) + 1
             
        res = pd.DataFrame()
        res["未匹配原因"] = df_fail["match_desc"]
        # 复制原始列
        for col in base_cols:
            res[col] = df_fail[col]
            
        res["标准化依据文件编码"] = df_fail["norm_code"]
        res["匹配状态"] = "未匹配"
        
        # 根据原因设置颜色标记
        # "工卡状态为..." -> 黄色，其他 -> 红色
        res["颜色标记"] = df_fail["match_desc"].apply(lambda x: "黄色" if "工卡状态" in str(x) else "红色")
        
        unmatch_rows = res.values.tolist()

    return match_rows, unmatch_rows, reason_counter


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
        df2.reset_index(drop=True, inplace=True)
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
logger.info(">>> 脚本开始执行 <<<")

# --- 连通性测试 ---
logger.info("正在进行环境连通性测试 (读取当前激活工作表 A1 单元格)...")
try:
    # 不指定 sheet_name，默认读取当前激活的 sheet，只读 A1
    test_df = xl("A1")
    logger.info(f"环境测试通过，读取到数据: {test_df.values.tolist() if not test_df.empty else '空'}")
except Exception as e:
    logger.info(f"警告: 环境连通性测试失败，可能是环境问题或没有激活的工作表。错误信息: {e}")
    logger.info("尝试继续执行主流程...")
# ------------------

logger.info("开始读取工作表数据……")
logger.info("提示：如果在此处卡顿过久，请检查工作表是否有大量空行（建议删除下方空白区域）")

# 可选优化：如果表格行数非常多且卡顿，可以尝试取消下行注释并指定范围，例如 "A1:Z5000"
# READ_RANGE_ORDERS = "A1:Z5000" 
READ_RANGE_ORDERS = None 

t0 = time.time()
if READ_RANGE_ORDERS:
    logger.info(f"正在读取工单表（范围 {READ_RANGE_ORDERS}）...")
    df_orders = xl(READ_RANGE_ORDERS, sheet_name=SHEET_ORDERS)
else:
    logger.info(f"正在读取工单表 {SHEET_ORDERS} (全表模式)...")
    df_orders = xl(sheet_name=SHEET_ORDERS)
logger.info(f"工单表读取完成，耗时 {time.time()-t0:.2f} 秒，原始行数: {len(df_orders)}")

t0 = time.time()
logger.info(f"正在读取标准库表 {SHEET_STD}...")
df_std = xl(sheet_name=SHEET_STD)
logger.info(f"标准库表读取完成，耗时 {time.time()-t0:.2f} 秒，原始行数: {len(df_std)}")

try:
    t0 = time.time()
    logger.info(f"正在读取工段分布表 {SHEET_SECTIONS}...")
    df_sections = xl(sheet_name=SHEET_SECTIONS)
    logger.info(f"工段分布表读取完成，耗时 {time.time()-t0:.2f} 秒")
except Exception:
    logger.info(f"警告：未找到工作表 {SHEET_SECTIONS}，将无法匹配工段信息。")
    df_sections = pd.DataFrame()

# 立即清理全空行，防止后续处理卡顿
logger.info("正在清理无效空行...")
df_orders.dropna(how='all', inplace=True)
df_std.dropna(how='all', inplace=True)
if not df_sections.empty:
    df_sections.dropna(how='all', inplace=True)

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

print("开始构建工段映射……")
section_map = build_section_mapping(df_sections)

base_cols = list(df_orders.columns)

# 使用新的向量化匹配函数
df_merged, mask_empty = match_all_vectorized(df_orders, df_std, orders_status_col)

# 使用新的结果生成函数
match_rows, unmatch_rows, unmatched_reason_counter = split_and_format_results(
    df_merged, mask_empty, section_map, orders_ac_col, orders_desc_col, orders_emp_id_col, orders_emp_name_col
)

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