# Quant

个人基金投资管理工具集 —— 交易记录管理、净值跟踪、持仓分析、实时行情快照。

## 安装

需要 [uv](https://docs.astral.sh/uv/)：

```bash
uv sync --extra dev
```

## 快速开始

### 1. 添加交易记录

```bash
# 买入（金额含手续费）
uv run python scripts/add_transaction.py add \
  --date 2026-06-02 \
  --product 002611 \
  --type buy \
  --amount 10000 \
  --notes "博时黄金ETF联接C 定投"

# 卖出（金额为到账金额）
uv run python scripts/add_transaction.py add \
  --date 2026-06-02 \
  --product 002611 \
  --type sell \
  --amount 5800 \
  --fee 15

# 批量补全 CSV 中缺失的 price/shares/fee
uv run python scripts/add_transaction.py fill           # 所有产品
uv run python scripts/add_transaction.py fill 002611    # 指定产品
```

> **交易日期规则**：基金以 15:00 为截止线，15:00 后下单按下一个交易日成交（周末/节假日顺延）。

**费率规则**（`src/GoldQuant/portfolio/fees.py`）：

- C 类基金买入费率 0%，A 类有申购费
- 卖出按持有天数阶梯：<7 天 1.5%，7-30 天 0.1%，≥30 天 0%

### 2. 查看持仓汇总

```bash
uv run python scripts/portfolio_summary.py
```

输出所有产品的累计投入、持仓市值、已实现/浮动盈亏、收益率及合计。

### 3. 查询基金数据

```bash
uv run python scripts/fund_info.py nav 002611                 # 最近 20 天净值走势
uv run python scripts/fund_info.py nav 002611 --days 60       # 最近 60 天
uv run python scripts/fund_info.py calendar 002611 05-01 05-28  # 区间交易日列表
uv run python scripts/fund_info.py stats 002611               # 近期统计（涨跌/回撤/均线/RSI）
uv run python scripts/fund_info.py lookup 002611              # 查本地记录的基金名
```

### 4. 实时行情快照

```bash
uv run python scripts/market_snapshot.py           # 完整快照（黄金+指数+ETF+建议）
uv run python scripts/market_snapshot.py --brief   # 简洁版（仅总结和建议）
uv run python scripts/market_snapshot.py --gold    # 只看黄金 ETF
```

盘中查看黄金 ETF、关键指数、持仓关联 ETF 的实时价格和涨跌。

### 5. 持仓分析报告

```bash
uv run python scripts/portfolio_report.py 002611          # 持仓分析
uv run python scripts/portfolio_report.py 002611 --no-html # 不生成 HTML 图表
```

输出累计投入/取出、当前持仓、总盈亏、年化 IRR、最大回撤，以及基于均线/RSI/布林带的策略信号。

## 数据文件

交易记录存储在 `data/portfolio/` 目录下，每个产品一个 CSV 文件：

```csv
date,product,type,amount,price,shares,fee,notes
2026-05-27,002611,buy,10000,3.0924,3232.04,0.0,博时黄金ETF联接C 定投
```

- `type`：`buy`（买入）、`sell`（卖出）、`dividend`（红利再投资）
- `amount`：买入时为总支付金额，卖出时为到账金额

## 项目结构

```text
Quant/
├── scripts/                     # 命令行工具
│   ├── add_transaction.py       # 交易记录管理（添加/补全）
│   ├── fund_info.py             # 基金数据查询
│   ├── market_snapshot.py       # 实时行情快照
│   ├── portfolio_report.py      # 持仓分析报告
│   └── portfolio_summary.py     # 投资组合汇总
├── src/GoldQuant/               # 核心库
│   ├── config.py                # 全局配置
│   ├── data/
│   │   ├── fetcher.py           # 数据获取（akshare → SGE/基金数据）
│   │   └── store.py             # CSV 本地存储
│   ├── portfolio/
│   │   ├── fees.py              # 费率规则
│   │   ├── models.py            # 数据模型（Transaction, Holding, PortfolioSummary）
│   │   └── tracker.py           # 持仓跟踪、净值获取、XIRR 计算
│   ├── analysis/
│   │   ├── indicators.py        # 技术指标（SMA/RSI/布林带/MACD/ATR）
│   │   └── signals.py           # 交易信号生成
│   ├── strategies/
│   │   ├── base.py              # 策略基类
│   │   └── examples.py          # 示例策略
│   ├── backtest/
│   │   ├── engine.py            # 回测引擎（逐笔模拟）
│   │   └── metrics.py           # 绩效指标（夏普比率/最大回撤/胜率）
│   └── visualization/
│       └── charts.py            # Plotly 交互图表
├── tests/                       # 测试（全部使用合成数据，无需网络）
├── data/
│   ├── raw/                     # 原始行情数据（Au99.99）
│   └── portfolio/               # 交易记录 CSV
└── CLAUDE.md                    # Claude Code 指令
```

## 运行测试

```bash
uv run pytest tests/ -v
```

所有测试使用合成数据，不依赖网络。

## 技术栈

- **数据源**：[akshare](https://github.com/akfamily/akshare)（东方财富/新浪实时行情 + 基金净值）
- **分析**：pandas, numpy
- **可视化**：plotly
- **测试**：pytest
