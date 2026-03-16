
import unittest
import pandas as pd
import re

# ==================== Logic to be tested (Copied from Script) ====================

def _norm(s):
    """
    Enhanced Normalization for Headers
    - Upper case
    - Remove all brackets (full/half width) and their contents? No, maybe just brackets.
    - Remove all whitespace (including newlines)
    - Remove punctuation
    """
    if s is None:
        return ""
    t = str(s)
    # Handle full-width characters first
    t = t.replace("\u00A0", " ").strip().upper()
    
    # Remove specific noise seen in user input: "(or...)"
    # Strategy: Just keep alphanumeric and chinese, remove all brackets and symbols
    # But user said: "控制号（or工卡号)" -> We want to match "控制号" or "工卡号"
    
    # Simple rigorous cleaning:
    # 1. Replace brackets with space
    t = t.replace("（", " ").replace("）", " ").replace("(", " ").replace(")", " ")
    # 2. Replace newlines with space
    t = t.replace("\n", " ").replace("\r", " ")
    # 3. Remove other punctuation
    t = t.replace("–", "").replace("—", "").replace("-", "")
    # 4. Remove all whitespace
    t = re.sub(r"\s+", "", t)
    
    return t

def deduplicate_columns(columns):
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

def ensure_header_logic(df):
    """
    Simulate the logic to find header in first N rows.
    """
    if df.empty:
        return df
        
    # Keywords to look for
    keys = {"控制号", "工卡号", "依据文件", "完成情况", "工时", "CONTROLNO", "STATUS"}
    
    # Helper to count matches
    def count_matches(row_values):
        row_norm = [_norm(v) for v in row_values]
        match_count = 0
        for val in row_norm:
            for k in keys:
                if k in val: # substring match
                    match_count += 1
                    break
        return match_count

    # 1. Check current columns
    current_matches = count_matches(df.columns)
    best_idx = -1
    max_matches = current_matches
    
    # 2. Scan first 10 rows
    rows_to_scan = min(len(df), 10)
    for i in range(rows_to_scan):
        row_matches = count_matches(df.iloc[i].values)
        if row_matches > max_matches:
            max_matches = row_matches
            best_idx = i
            
    # 3. If a better row is found, promote it
    if best_idx != -1:
        # print(f"Found better header at row {best_idx}, matches: {max_matches}")
        new_header = df.iloc[best_idx].values
        # Data starts from best_idx + 1
        df_new = df.iloc[best_idx+1:].copy()
        df_new.columns = deduplicate_columns(new_header)
        return df_new
        
    return df

def locate_col_logic(df, candidates):
    cand_norm = {_norm(c) for c in candidates}
    # 1. Exact match (normalized)
    for col in df.columns:
        if _norm(col) in cand_norm:
            return col
            
    # 2. Partial match
    for col in df.columns:
        nc = _norm(col)
        for c in cand_norm:
            if c in nc: 
                return col
    return None

# ==================== Test Case ====================

class TestHeaderDetection(unittest.TestCase):
    
    def setUp(self):
        # Scenario: Header is at row index 1 (2nd row), with garbage above
        # Column 2: "控制号（or工卡号)"
        # Column 3: "完成\n情况"
        data = [
            ["无关信息", "Title", "", ""],
            ["序号", "机号", "控制号（or工卡号)", "完成\n情况"], # Real Header
            [1, "B-1234", "AMM 24-00-00", "一工段完成"],
            [2, "B-5678", "AMM 25-00-00", "未完成"],
        ]
        # Create DF with default integer columns
        self.df_messy = pd.DataFrame(data)
        
    def test_norm(self):
        # Test specific user cases
        self.assertEqual(_norm("控制号（or工卡号)"), "控制号OR工卡号")
        self.assertEqual(_norm("完成\n情况"), "完成情况")
        self.assertEqual(_norm("   序号   "), "序号")
        
    def test_ensure_header(self):
        # Should detect row 1 as header
        df_clean = ensure_header_logic(self.df_messy)
        
        # Check columns
        cols = df_clean.columns.tolist()
        # Verify "控制号（or工卡号)" became a column
        self.assertIn("控制号（or工卡号)", cols)
        self.assertIn("完成\n情况", cols)
        
        # Verify data content (AMM 24-00-00 should be in first row)
        self.assertEqual(df_clean.iloc[0]["控制号（or工卡号)"], "AMM 24-00-00")
        
    def test_locate_col(self):
        df_clean = ensure_header_logic(self.df_messy)
        
        # Test finding Control No
        col_control = locate_col_logic(df_clean, ["控制号", "工卡号"])
        self.assertEqual(col_control, "控制号（or工卡号)")
        
        # Test finding Status
        col_status = locate_col_logic(df_clean, ["完成情况", "状态"])
        self.assertEqual(col_status, "完成\n情况")

if __name__ == "__main__":
    unittest.main()
