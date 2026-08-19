"""Translation of Plaid account taxonomy into our ``AccountType`` enum.

Plaid reports ``type``/``subtype`` pairs (e.g. ``investment``/``401k``). We only
model three buckets, so everything unrecognised falls back to ``brokerage``.
"""
from __future__ import annotations

from app.models import AccountType

_RETIREMENT_401K_SUBTYPES = {"401k", "401a", "403b"}
_ROTH_SUBTYPES = {"ira", "roth", "roth 401k"}


def map_account_type(plaid_type: str | None, plaid_subtype: str | None) -> AccountType:
    """Map a Plaid ``(type, subtype)`` pair to an ``AccountType``.

    Roth wins over the 401k bucket, so ``"roth 401k"`` maps to ``roth``.
    Matching is case-insensitive; unknown or missing values yield ``brokerage``.
    """
    subtype = (plaid_subtype or "").strip().lower()
    if subtype in _ROTH_SUBTYPES:
        return AccountType.roth
    if subtype in _RETIREMENT_401K_SUBTYPES:
        return AccountType._401k
    return AccountType.brokerage
