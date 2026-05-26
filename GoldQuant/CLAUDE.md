# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install in editable mode
pip install -e ".[dev]"

# Run all tests (no network calls — all tests use synthetic data)
pytest tests/ -v

# Run a single test file
pytest tests/test_indicators.py -v
```

## Architecture

**Data flow**: `SgeFetcher` (AkShare) → `LocalDataStore` (CSV) → indicators (pure functions) → `Strategy` (signals) → `BacktestEngine` (bar-by-bar loop) → `compute_metrics` → Plotly charts.

### Strategy contract

Every strategy subclasses `Strategy` (in `strategies/base.py`) and implements two methods:

- `init(data) -> DataFrame` — attach indicator columns to a copy of the data, return it.
- `next(i, row, context) -> int` — called per bar. Return `1` (enter/buy), `-1` (exit/sell), `0` (hold). `context` is a mutable dict the engine reads/writes (keys: `position`, `entry_price`). The engine sets `context["position"]` after executing entries/exits — strategies should use it for state-aware logic.

Subclasses auto-register in `Strategy.registry` by class name.

### Indicators are pure functions

All functions in `analysis/indicators.py` take a DataFrame and return a **new** DataFrame with added columns (never mutate the input). They assume a `close` column exists and the data is sorted chronologically. This enables chaining:

```python
df = add_rsi(add_sma(df, 20), 14)
```

### Backtest engine

`BacktestEngine.run()` does bar-by-bar simulation (not vectorized) to avoid lookahead bias. It tracks cash + units, applies slippage on entry/exit prices, deducts commission from PnL, and records `TradeRecord` dataclasses for every completed round-trip. Returns a dict with `equity_curve` (DataFrame), `trades` (list), `strategy`, `symbol`, `initial_capital`.

`compute_metrics()` converts that dict into a `BacktestResult` dataclass with Sharpe ratio (annualized, sqrt(252)), max drawdown, win rate, profit factor, etc.

### Config

`GoldQuantConfig` is a `@dataclass` in `config.py` holding all tunable parameters — data dir, commission, indicator periods, etc. All components accept an optional `config` argument and default to a fresh `GoldQuantConfig()`.

### Data layer

- `SgeFetcher.fetch_hist()` wraps `akshare.spot_hist_sge()` — normalizes column names to lowercase, coerces date column, adds symbol column, sorts chronologically. Retries with exponential backoff on failure.
- `LocalDataStore` handles CSV round-trips under `data/raw/`. `update()` merges new data with cached data, deduplicating on `date`.

## Response Language

- Default to Chinese in responses.
- If the user explicitly asks for another language, follow the user's request.

## General Assistant Behavior

From now on, act as my expert assistant with access to all your reasoning and knowledge. Always provide:

- A clear, direct answer to my request.
- A step-by-step explanation of how you got there.
- Alternative perspectives or solutions I might not have thought of.
- A practical summary or action plan I can apply immediately.

Never give vague answers. If the question is broad, break it into parts. If I ask for help, act like a professional in that domain (teacher, coach, engineer, doctor, etc.). Push your reasoning to 100% of your capacity.

## Git 提交规范

- 提交信息格式：`<type>: <简短描述>`，描述默认使用中文。若用户明确要求使用其他语言（如英文），则以用户要求为准。
- type 取值：
  - feat: 新功能
  - fix: 修复 bug
  - docs: 仅文档变更
  - style: 代码风格变动（不影响代码逻辑，如格式化、缩进等）
  - refactor: 代码重构（既不是新增功能也不是修复 bug）
  - perf: 性能优化
  - test: 添加或修改测试
  - chore: 杂项（构建过程、依赖、辅助工具等）
  - build: 构建系统或外部依赖项变更
  - ci: 持续集成配置变更
  - revert: 回滚之前的提交
- 每次 commit 仅包含与该提交主题直接相关的文件更改，避免一次 commit 包含过多内容，便于后续问题排查。

# andrej-karpathy-style-guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.