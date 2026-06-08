---
name: add-regular-investment
description: This skill should be used when the user provides fund transaction details for batch entry, including regular investment plans (定投) with weekly/daily frequency, overlapping phases (并行), or individual buy/sell transactions. Triggered by phrases like "定投", "每周/每日定投", "批量录入", "新增交易", "添加记录", or when the user specifies fund code + amount + date range + frequency.
version: 1.0.0
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - WebSearch
---

# 定投交易录入

批量添加基金的定投交易记录到 CSV。

## 流程

### 1. 确认基金信息

如果用户未提供基金名称，通过 `WebSearch` 搜索基金代码获取全称，填入 `--notes`。

### 2. 获取交易日历

```bash
python scripts/fund_info.py calendar <code> <start_date> <end_date>
```

从输出中提取实际交易日，排除周末和节假日。

### 3. 确定交易日期

- 场外基金以 **15:00** 为截止线，15:00 后下单按 **下一个交易日** 成交
- 周末/节假日顺延到下一交易日
- QDII 基金（纳斯达克、标普等）净值有 **T+1 延迟**，当天数据可能未出——只录入 NAV 已可用的日期

### 4. 判断手续费

- **C 类基金**（代码名含 "C" 或用户明确说是 C 类）：申购费 0%，**不传 `--fee`**
- **A 类基金**（代码名含 "A"）：有申购费，用户通常告知具体金额，传 `--fee <金额>`
- 不确定时，检查 `src/Quantfolio/portfolio/fees.py` 中的 `BUY_FEE_RATES` 字典

### 5. 批量执行

```bash
for d in <date1> <date2> ...; do
  python scripts/add_transaction.py add \
    --date "$d" \
    --product <code> \
    --type buy \
    --amount <amount> \
    --fee <fee> \
    --notes "<fund_name> 定投"
done
```

- 若有多阶段并行（如同时有每周和每日），**分开运行**，每个阶段一个 for 循环
- 每个阶段用不同的 `--notes` 区分（如 "每周定投50"、"每日定投20"）

### 6. 确认

```bash
python scripts/portfolio_summary.py | grep <code>
```

验证累计投入金额和笔数是否符合预期。

## 关键规则

- 基金代码 **始终保留前导零**（如 008987，不是 8987）
- QDII 净值只有截止到 `fund_info.py calendar` 输出的最后一个日期可录入，之后的跳过并在总结中标注 "待补"
- 买入 `--amount` = 总支付金额（含手续费）
- 当前日期 `!`date +%F``
