/**
 * WPS AirScript 脚本：匹配结果与未匹配结果 排序、合并与着色 (增强版)
 * 
 * 功能：
 * 1. [匹配结果]：按工段合并 A 列，随机着色；最后一行“汇总工时”合并 A-J 列并居中。
 * 2. [未匹配结果]：按未匹配原因合并 A 列，随机着色。
 * 
 * 使用说明：
 * 1. 复制全部代码。
 * 2. 粘贴到 WPS AirScript 编辑器。
 * 3. 点击“运行”按钮。
 */

// 立即运行主函数
Main();

function Main() {
    console.log("脚本开始运行...");
    
    // 处理“匹配结果”工作表
    ProcessSheet("匹配结果", true);
    
    // 处理“未匹配结果”工作表
    ProcessSheet("未匹配结果", false);
    
    alert("所有工作表处理完成！");
}

/**
 * 处理单个工作表的通用函数
 * @param {string} sheetName 工作表名称
 * @param {boolean} isMatchSheet 是否为“匹配结果”表（用于特殊处理汇总行）
 */
function ProcessSheet(sheetName, isMatchSheet) {
    var sheet;
    
    // 1. 获取工作表
    try {
        if(Application.Worksheets.Count > 0) {
            try { sheet = Application.Worksheets.Item(sheetName); } catch(e){}
        }
        if(!sheet) {
            try { sheet = Sheets.Item(sheetName); } catch(e){}
        }
        
        if (!sheet) {
            console.log("跳过：找不到名为【" + sheetName + "】的工作表。");
            return;
        }
        sheet.Activate();
    } catch (e) {
        console.log("获取工作表失败：" + sheetName + "，错误：" + e.message);
        return;
    }

    // 2. 确定数据范围
    var lastRow = sheet.Cells(sheet.Rows.Count, 1).End(-4162).Row; // xlUp
    
    // 如果是匹配表，最后一行可能是汇总行（位于B列），所以也要检查B列
    if (isMatchSheet) {
        var lastRowB = sheet.Cells(sheet.Rows.Count, 2).End(-4162).Row;
        if (lastRowB > lastRow) {
            lastRow = lastRowB;
        }
    }

    var lastCol = sheet.Cells(1, sheet.Columns.Count).End(-4159).Column; // xlToLeft
    
    if (lastRow < 2) {
        console.log(sheetName + " 数据不足，跳过处理。");
        return;
    }

    // 3. 特殊处理：如果是“匹配结果”表，处理汇总行（支持多行汇总）
    var sortLastRow = lastRow;
    if (isMatchSheet) {
        // 从最后一行向上扫描，找到所有包含“汇总”的行
        for (var r = lastRow; r >= 2; r--) {
            var cellValA = sheet.Cells(r, 1).Text;
            var cellValB = sheet.Cells(r, 2).Text;
            
            if (cellValA.indexOf("汇总") > -1 || cellValB.indexOf("汇总") > -1) {
                // 这是一个汇总行
                sortLastRow = r - 1; // 排序范围收缩，排除此汇总行
                
                // 确保“汇总”文字在 A 列 (合并时通常保留左上角的值)
                if (cellValA.indexOf("汇总") == -1 && cellValB.indexOf("汇总") > -1) {
                    sheet.Cells(r, 1).Value = cellValB;
                    sheet.Cells(r, 2).Value = ""; // 清空B列
                }

                // 合并汇总行 A-J (1-10列)
                try {
                    var sumRange = sheet.Range(sheet.Cells(r, 1), sheet.Cells(r, 10));
                    sumRange.Merge();
                    sumRange.HorizontalAlignment = -4108; // xlCenter
                    sumRange.VerticalAlignment = -4108;   // xlCenter
                    console.log("已合并汇总行：" + r);
                } catch(e) {
                    console.log("合并汇总行失败：" + e.message);
                }
            } else {
                // 一旦遇到非汇总行，停止扫描（假设汇总行都集中在底部）
                break;
            }
        }
    }

    // 4. 取消 A 列旧的合并（防止排序报错）
    if (sortLastRow >= 2) {
        sheet.Range("A2:A" + sortLastRow).UnMerge();

        // 5. 排序 (按 A 列升序)
        // 注意：Python 脚本已经排过序了，这里再次排序是为了确保 AirScript 逻辑闭环
        // 如果 Python 已经排好序，这里的 Sort 其实可以注释掉，但为了保险起见保留
        var sortRange = sheet.Range(sheet.Cells(1, 1), sheet.Cells(sortLastRow, lastCol));
        
        try {
            sortRange.Sort(
                sheet.Range("A1"), // Key1
                1,                 // Order1: 1 = xlAscending
                undefined, undefined, undefined, undefined, undefined,
                1                  // Header: 1 = xlYes
            );
        } catch (e) {
            console.log(sheetName + " 排序出错：" + e.message);
        }
        
        // 6. 合并与着色 A 列
        MergeAndColorColumn(sheet, sortLastRow);
    }
}

/**
 * 合并并着色 A 列的通用逻辑
 */
function MergeAndColorColumn(sheet, lastRow) {
    Application.DisplayAlerts = false; // 关闭警告
    
    try {
        var startRow = 2;
        // 获取 A 列数据 (二维数组)
        var data = sheet.Range("A1:A" + (lastRow + 1)).Value(); 
        
        for (var r = 2; r <= lastRow + 1; r++) {
            // 获取当前值 (处理边界)
            var currentVal = (r <= lastRow) ? data[r-1][0] : "###END###";
            var startVal = data[startRow-1][0];
            
            // 强制转字符串比较
            if (String(currentVal) != String(startVal)) {
                var endRow = r - 1;
                var rangeToProcess = sheet.Range("A" + startRow + ":A" + endRow);
                
                // 执行合并 (多行时)
                if (endRow > startRow) {
                    rangeToProcess.Merge();
                }
                
                // 居中 (单行或多行都居中)
                rangeToProcess.HorizontalAlignment = -4108; // xlCenter
                rangeToProcess.VerticalAlignment = -4108;   // xlCenter
                
                // 颜色逻辑
                // 如果是“未匹配结果”表，A列是原因；如果是“匹配结果”表，A列是工段
                // 统一逻辑：随机浅色，但排除空值
                
                if (startVal && String(startVal).trim() != "") {
                    // 随机浅色
                    var R = 205 + Math.floor(Math.random() * 50);
                    var G = 205 + Math.floor(Math.random() * 50);
                    var B = 205 + Math.floor(Math.random() * 50);
                    rangeToProcess.Interior.Color = R + (G * 256) + (B * 65536);
                }

                // 下一段
                startRow = r;
            }
        }
        console.log("列合并着色完成。");
    } catch (e) {
        console.log("合并着色出错：" + e.message);
    } finally {
        Application.DisplayAlerts = true;
    }
}
