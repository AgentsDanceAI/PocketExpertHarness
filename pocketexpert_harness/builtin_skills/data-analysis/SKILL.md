---
name: data-analysis
description: 用 Python 分析工作区里的表格数据 (CSV / Excel / JSON): 先看数据长什么样, 再算指标、找规律, 必要时出图存成文件。用户给了数据文件、要"分析 / 统计 / 画个图"时使用。
triggers: [分析数据, 统计, 画图, 图表, csv, excel, data analysis]
---

# 数据分析

## 做法
1. 先 list_files 找到数据文件, 再用 run_python 读前几行、看列名、类型、缺失值和行数 —— 看清楚再动手, 别猜列名。
2. 每一步计算都 print 出结果, 用真实算出来的数说话; 不要心算大数。
3. 清洗 (去重、缺失值、类型转换) 做了什么要在回答里交代。
4. 出图: 用 matplotlib, 中文标签先设字体 (`plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", "SimHei"]`), 存成 PNG 到工作区, 回答里写文件名。
5. 环境里没有某个库就换一种写法 (pandas 不在就用 csv 模块), 不要反复重试同一句 import。

## 交付格式
- 数据概况 (几行几列、时间范围)
- 3–5 条发现, 每条带具体数字
- 生成的文件列表
- 如果结论受数据质量影响, 单独说明
