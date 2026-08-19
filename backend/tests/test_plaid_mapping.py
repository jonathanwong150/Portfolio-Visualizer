"""Tests for the Plaid account taxonomy → AccountType mapping."""
from __future__ import annotations

import pytest

from app.models import AccountType
from app.plaid_mapping import map_account_type


@pytest.mark.parametrize(
    "subtype,expected",
    [
        ("brokerage", AccountType.brokerage),
        ("ira", AccountType.roth),
        ("roth", AccountType.roth),
        ("roth 401k", AccountType.roth),  # roth wins over the 401k bucket
        ("401k", AccountType._401k),
        ("401a", AccountType._401k),
        ("403b", AccountType._401k),
        ("hsa", AccountType.brokerage),   # unknown -> brokerage
        (None, AccountType.brokerage),
    ],
)
def test_subtype_mapping(subtype, expected):
    assert map_account_type("investment", subtype) is expected


@pytest.mark.parametrize("subtype", ["401K", "Roth", "IRA", " 403b "])
def test_mapping_is_case_and_whitespace_insensitive(subtype):
    assert map_account_type("INVESTMENT", subtype) is not AccountType.brokerage


def test_missing_type_and_subtype_defaults_to_brokerage():
    assert map_account_type(None, None) is AccountType.brokerage
