from __future__ import annotations

from decimal import Decimal

from .models import Selection, Slip


class ValidationError(ValueError):
    """Invalid user-entered betting data."""


def validate_selection(selection: Selection) -> None:
    if not selection.match_id.strip() or not selection.player.strip():
        raise ValidationError("match and player are required")
    if not selection.opponent.strip() or selection.player == selection.opponent:
        raise ValidationError("a selection needs a different opponent")
    if selection.odds <= Decimal("1"):
        raise ValidationError("decimal odds must be greater than 1")
    if selection.user_probability is not None and not Decimal("0") < selection.user_probability <= Decimal("1"):
        raise ValidationError("probability must be between 0 and 1")


def validate_selection_for_slip(slip: Slip, selection: Selection) -> None:
    validate_selection(selection)
    same_match = [s for s in slip.selections if s.match_id == selection.match_id]
    if any(s.player == selection.player for s in same_match):
        raise ValidationError("that selection is already on the slip")
    if same_match:
        raise ValidationError("conflicting selections for the same match are not allowed")


def validate_stake(stake: Decimal, limit: Decimal | None = None) -> Decimal:
    value = Decimal(str(stake))
    if value <= 0:
        raise ValidationError("stake must be greater than zero")
    if limit is not None and value > limit:
        raise ValidationError(f"stake exceeds spending limit of {limit}")
    return value
