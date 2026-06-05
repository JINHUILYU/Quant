---
name: verify-transactions
description: This skill should be used when the user asks to verify, check, or validate transaction data. Triggered by phrases like "校验交易", "检查数据", "核对 buy/sell 记录", "验证手续费", "有没有问题", or when new transactions have just been added and need confirmation.
version: 1.0.0
allowed-tools:
  - Bash
  - Read
  - Edit
  - Write
---

# 交易数据校验

验证指定日期范围内的 buy/sell 记录的数据正确性。

## 流程

### 1. 确定校验范围

- 如果用户指定了日期范围，使用该范围
- 如果用户只说"这周"或"最近"，用 `scripts/recent_txns.py -d N` 先列出所有记录
- 默认检查最近 7 天的所有新增 buy 记录

### 2. 验证公式

对每笔 buy 记录验证：

```
正确 shares = round((amount - fee) / price, 2)
```

用 Python 精确计算并对比 CSV 中的值：

```bash
python3 -c "
price = <price>
amount = <amount>
fee = <fee>
expected = round((amount - fee) / price, 2)
print(f'CSV shares=<csv_shares>, 验算={expected}', '✅' if expected == <csv_shares> else '⚠️ 不匹配')
"
```

### 3. 检查点

| 检查项 | 方法 |
|--------|------|
| **A 类申购费是否缺失** | 对比同基金历史记录，如果其他行都有 fee 而某行 fee=0，标记为异常 |
| **shares 与 fee 是否一致** | 若 fee>0 但 shares = round(amount/price, 2)（即按 fee=0 算出），标记为不一致 |
| **金额/份额是否合理** | 与同基金相邻记录对比，金额突变或份额异常标记 |

### 4. 输出报告

以表格列出所有问题：

```
| 基金 | 日期 | 问题 | 当前值 | 正确值 |
```

### 5. 修正（需用户确认）

对于确认需要修正的行，直接编辑 CSV 中对应行：

```bash
python3 -c "
# 直接在 python 中读取 CSV → 修改 → 写回
"
```

或使用 `sed` 精确替换行。

修正后运行 `python scripts/portfolio_summary.py` 确认合计一致。

## 关键规则

- **只修改确有问题的字段**，不要改动其他列
- A 类基金的历史 fee 模式就是当前 fee 的参考基准
- 修正前向用户展示完整的问题列表，确认后再执行
- 备份思想：如果是大量修改，先 `cp file.csv file.csv.bak`
