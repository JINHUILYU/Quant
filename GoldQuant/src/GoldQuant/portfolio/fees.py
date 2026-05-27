"""Fund fee calculation and FIFO lot tracking."""

from __future__ import annotations

from dataclasses import dataclass

from GoldQuant.portfolio.models import Transaction

# ---------------------------------------------------------------------------
# Configurable fee rates
# ---------------------------------------------------------------------------

# Subscription fee (申购费率) per product. C-class funds are typically 0%.
BUY_FEE_RATES: dict[str, float] = {
    "002611": 0.0,
    "000217": 0.0,
    "009505": 0.0,
    "008987": 0.0,
}

# Redemption fee (赎回费率) tiers: (max_days_exclusive, rate)
SELL_FEE_TIERS: list[tuple[int, float]] = [
    (7, 0.015),     # < 7 days: 1.5%
    (30, 0.001),    # 7-30 days: 0.1%
    (float("inf"), 0.0),
]


def get_buy_fee_rate(product: str) -> float:
    """Subscription fee rate for a product (default 0)."""
    return BUY_FEE_RATES.get(product, 0.0)


def get_sell_fee_rate(holding_days: int) -> float:
    """Redemption fee rate based on holding days."""
    for max_days, rate in SELL_FEE_TIERS:
        if holding_days < max_days:
            return rate
    return 0.0


# ---------------------------------------------------------------------------
# FIFO lot tracking
# ---------------------------------------------------------------------------


@dataclass
class Lot:
    date: str   # "YYYY-MM-DD"
    shares: float
    price: float


def compute_lots(txns: list[Transaction]) -> list[Lot]:
    """Build FIFO holding lots from sorted transactions."""
    lots: list[Lot] = []
    for t in sorted(txns, key=lambda x: x.date):
        if t.type == "buy":
            lots.append(Lot(
                date=t.date.strftime("%Y-%m-%d"),
                shares=t.shares,
                price=t.price,
            ))
        else:  # sell — consume FIFO
            remaining = t.shares
            while remaining > 0 and lots:
                if lots[0].shares <= remaining:
                    remaining -= lots[0].shares
                    lots.pop(0)
                else:
                    lots[0].shares -= remaining
                    remaining = 0
    return lots


# ---------------------------------------------------------------------------
# Buy / Sell calculation
# ---------------------------------------------------------------------------


def compute_buy(amount: float, price: float, product: str) -> tuple[float, float]:
    """Calculate (shares, fee) for a buy.

    ``amount`` is the total cash paid (gross, including fee).
    """
    fee_rate = get_buy_fee_rate(product)
    net_amount = amount / (1.0 + fee_rate)
    fee = round(amount - net_amount, 2)
    shares = round(net_amount / price, 2)
    return shares, fee


def compute_sell(
    amount: float,
    price: float,
    product: str,
    txns: list[Transaction],
    sell_date: str,
) -> tuple[float, float] | None:
    """Calculate (shares, fee) for a sell.

    ``amount`` is the net cash received (after fee deduction).
    ``sell_date`` is "YYYY-MM-DD", used as the reference for holding-period fees.
    Returns None if there aren't enough shares to fulfil the redemption.
    """
    # Step 1: current FIFO lots
    lots = compute_lots(txns)
    total_held = sum(l.shares for l in lots)
    if total_held <= 0:
        return None

    # Step 2: iterate — guess shares → compute weighted fee → refine
    fee_rate_guess = 0.0
    for _ in range(3):
        gross = amount / (1.0 - fee_rate_guess)
        shares_needed = round(gross / price, 2)

        if shares_needed > total_held:
            # Not enough shares — use all
            shares_needed = total_held
            fee_rate_guess = _fifo_weighted_rate(lots, shares_needed, sell_date)
            gross = shares_needed * price
            fee = round(gross * fee_rate_guess, 2)
            net = gross - fee
            if net >= amount:
                return shares_needed, fee
            return shares_needed, round(gross * fee_rate_guess, 2)

        fee_rate_guess = _fifo_weighted_rate(lots, shares_needed, sell_date)

    gross = round(shares_needed * price, 2)
    fee = round(gross * fee_rate_guess, 2)
    return shares_needed, fee


def _fifo_weighted_rate(lots: list[Lot], shares_to_sell: float, ref_date: str) -> float:
    """Weighted-average redemption fee rate for selling ``shares_to_sell`` via FIFO."""
    remaining = shares_to_sell
    weighted = 0.0

    for lot in lots:
        if remaining <= 0:
            break
        taken = min(lot.shares, remaining)
        days = (_days_between(lot.date, ref_date) or 180)
        rate = get_sell_fee_rate(days)
        weighted += taken * rate
        remaining -= taken

    if shares_to_sell <= 0:
        return 0.0
    return weighted / shares_to_sell


def _days_between(start: str, end: str) -> int:
    from datetime import datetime
    d1 = datetime.strptime(start, "%Y-%m-%d")
    d2 = datetime.strptime(end, "%Y-%m-%d")
    return (d2 - d1).days
