from __future__ import annotations

import random
from decimal import Decimal, ROUND_HALF_UP
from itertools import combinations
from typing import Iterable

from .models import BetType, Selection, Slip
from .validation import validate_stake

ONE = Decimal("1")


def combined_odds(selections: Iterable[Selection]) -> Decimal:
    result = ONE
    for selection in selections:
        result *= selection.odds
    return result


def implied_probability(odds: Decimal) -> Decimal:
    if odds <= ONE:
        raise ValueError("odds must be greater than 1")
    return ONE / odds


def bookmaker_margin(selections: Iterable[Selection]) -> Decimal:
    values = list(selections)
    if not values:
        return Decimal("0")
    return sum((implied_probability(s.odds) for s in values), Decimal("0")) - ONE


def value_indicator(selection: Selection) -> bool | None:
    if selection.user_probability is None:
        return None
    return selection.user_probability > implied_probability(selection.odds)


def _return_for(selections: list[Selection], stake: Decimal) -> Decimal:
    return stake * combined_odds(selections)


def potential_returns(slip: Slip, stake: Decimal | None = None) -> list[Decimal]:
    if not slip.selections:
        raise ValueError("cannot calculate an empty slip")
    amount = validate_stake(stake if stake is not None else slip.stake, slip.spending_limit)
    selections = slip.selections
    if slip.bet_type == BetType.SINGLE:
        return [_return_for([s], amount / len(selections)) for s in selections]
    if slip.bet_type == BetType.SYSTEM:
        if not 1 < slip.system_size <= len(selections):
            raise ValueError("system size must be between 2 and the number of selections")
        unit = amount / Decimal(len(list(combinations(selections, slip.system_size))))
        return [_return_for(list(group), unit) for group in combinations(selections, slip.system_size)]
    return [_return_for(selections, amount)]


def round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def simulate(slip: Slip, trials: int = 1000, seed: int | None = None) -> Decimal:
    if trials < 1:
        raise ValueError("trials must be positive")
    rng = random.Random(seed)
    wins = 0
    for _ in range(trials):
        if all(rng.random() < implied_probability(s.odds) for s in slip.selections):
            wins += 1
    return Decimal(wins) / Decimal(trials)
