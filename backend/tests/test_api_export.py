"""API-level tests for the CSV export endpoints."""
from __future__ import annotations


def test_holdings_export_serves_csv_as_an_attachment(client):
    res = client.get("/export/holdings.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["content-disposition"] == 'attachment; filename="holdings.csv"'


def test_exposure_export_serves_csv_as_an_attachment(client):
    res = client.get("/export/exposure.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert res.headers["content-disposition"] == 'attachment; filename="exposure.csv"'


def test_holdings_export_body_starts_with_the_header_row(client):
    body = client.get("/export/holdings.csv").text
    assert body.splitlines()[0] == "ticker,name,account_type,shares,price,value,cost_basis"


def test_exposure_export_body_starts_with_the_header_row(client):
    body = client.get("/export/exposure.csv").text
    first = body.splitlines()[0]
    assert first == "ticker,name,value,weight,direct_value,via_etf_value,source_etfs,is_unresolved"


def test_exports_carry_the_mock_portfolio_rows(client):
    """The default broker is MockBroker, so both exports have real content."""
    holdings = client.get("/export/holdings.csv").text.splitlines()
    exposure = client.get("/export/exposure.csv").text.splitlines()
    assert len(holdings) > 1
    assert len(exposure) > 1
