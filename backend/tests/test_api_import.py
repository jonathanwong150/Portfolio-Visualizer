"""API-level tests for the CSV import endpoints."""
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _upload(client, name: str, filename: str = "positions.csv"):
    body = (FIXTURES / name).read_bytes()
    return client.post(
        "/import/preview", files={"file": (filename, body, "text/csv")}
    )


def test_preview_returns_a_parsed_portfolio_without_writing(client):
    res = _upload(client, "fidelity_positions.csv")
    assert res.status_code == 200
    body = res.json()

    assert body["source_format"] == "fidelity"
    assert {h["ticker"] for h in body["holdings"]} == {"NVDA", "SPY", "VTI", "BRK.B", "SPAXX"}
    assert {a["name"] for a in body["accounts"]} == {"Individual", "ROTH IRA"}

    # Preview must not persist: accounts stay empty until commit.
    assert client.get("/accounts").json()["accounts"] == []


def test_preview_reports_skipped_rows(client):
    body = _upload(client, "robinhood_activity.csv").json()
    reasons = " ".join(s["reason"] for s in body["skipped"]).lower()
    assert "option" in reasons
    assert "crypto" in reasons
    assert any("split" in w.lower() for w in body["warnings"])


def test_preview_rejects_an_unrecognised_file_with_400(client):
    res = client.post(
        "/import/preview", files={"file": ("junk.csv", b"alpha,beta\n1,2\n", "text/csv")}
    )
    assert res.status_code == 400
    assert "header" in res.json()["detail"].lower()


def test_preview_rejects_a_non_utf8_file_without_a_500(client):
    res = client.post(
        "/import/preview", files={"file": ("bad.csv", b"\xff\xfe\x00binary", "text/csv")}
    )
    assert res.status_code == 400


def test_commit_writes_a_snapshot_that_the_app_then_serves(client):
    preview = _upload(client, "fidelity_positions.csv").json()

    res = client.post(
        "/import/commit",
        json={"holdings": preview["holdings"], "accounts": preview["accounts"]},
    )
    assert res.status_code == 200
    result = res.json()
    assert result["accounts"] == 2
    assert result["holdings"] == 5

    accounts = client.get("/accounts").json()["accounts"]
    assert {a["name"] for a in accounts} == {"Individual", "ROTH IRA"}
    assert {a["type"] for a in accounts} == {"brokerage", "roth"}


def test_commit_honours_a_corrected_account_type(client):
    preview = _upload(client, "fidelity_positions.csv").json()
    # The user overrides the guess in the preview UI.
    for account in preview["accounts"]:
        if account["name"] == "Individual":
            account["account_type"] = "401k"

    client.post(
        "/import/commit",
        json={"holdings": preview["holdings"], "accounts": preview["accounts"]},
    )

    by_name = {a["name"]: a for a in client.get("/accounts").json()["accounts"]}
    assert by_name["Individual"]["type"] == "401k"


def test_reimporting_updates_accounts_rather_than_duplicating_them(client):
    preview = _upload(client, "fidelity_positions.csv").json()
    payload = {"holdings": preview["holdings"], "accounts": preview["accounts"]}

    client.post("/import/commit", json=payload)
    client.post("/import/commit", json=payload)

    accounts = client.get("/accounts").json()["accounts"]
    assert len(accounts) == 2


def test_two_commits_produce_two_points_of_net_worth_history(client):
    preview = _upload(client, "fidelity_positions.csv").json()
    payload = {"holdings": preview["holdings"], "accounts": preview["accounts"]}

    client.post("/import/commit", json=payload)
    client.post("/import/commit", json=payload)

    # Holdings are append-only, so each commit is its own snapshot.
    points = client.get("/portfolio/history").json()["points"]
    assert len(points) == 2


def test_imported_prices_drive_net_worth_not_synthesized_ones(client):
    """The bug this guards: the seed provider prices every ticker at ~$106.

    A $1.00 money-market fund became $106 a share, inflating net worth 4x.
    """
    preview = _upload(client, "fidelity_positions.csv").json()
    client.post(
        "/import/commit",
        json={"holdings": preview["holdings"], "accounts": preview["accounts"]},
    )

    # 7,300 + 19,236 + 12,510 + 2,460.50 + 1,502.34 straight off the statement.
    expected = 43_008.84
    assert client.get("/portfolio/summary").json()["net_worth"] == pytest.approx(expected)


def test_a_dollar_priced_sweep_fund_is_not_revalued(client):
    preview = _upload(client, "fidelity_positions.csv").json()
    client.post(
        "/import/commit",
        json={"holdings": preview["holdings"], "accounts": preview["accounts"]},
    )

    exposures = {c["ticker"]: c for c in client.get("/exposure/companies").json()}
    # 1502.34 shares at the statement's $1.00, not the seed's ~$106.
    assert exposures["SPAXX"]["value"] == pytest.approx(1502.34)


def test_a_ticker_with_no_imported_price_still_gets_one(client):
    """Canonical uploads carry no prices, so the fallback must still work."""
    body = b"ticker,shares,account\nNVDA,10,Individual\n"
    preview = client.post(
        "/import/preview", files={"file": ("t.csv", body, "text/csv")}
    ).json()
    client.post(
        "/import/commit",
        json={"holdings": preview["holdings"], "accounts": preview["accounts"]},
    )

    assert client.get("/portfolio/summary").json()["net_worth"] > 0


def test_template_is_downloadable_and_parses_as_canonical(client):
    res = client.get("/import/template.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")

    # The template we hand out must survive our own parser.
    echo = client.post(
        "/import/preview",
        files={"file": ("template.csv", res.content, "text/csv")},
    )
    assert echo.status_code == 200
    assert echo.json()["source_format"] == "canonical"
