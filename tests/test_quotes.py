import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from quotes import (  # noqa: E402
    to_yahoo_symbol,
    parse_chart_json,
    compute_change,
    enrich_stock_prices,
)


# --- to_yahoo_symbol ---


def test_to_yahoo_symbol_plain_code():
    assert to_yahoo_symbol("6472") == "6472.T"


def test_to_yahoo_symbol_dot_t_suffix():
    assert to_yahoo_symbol("6472.T") == "6472.T"


def test_to_yahoo_symbol_dot_jp_suffix():
    assert to_yahoo_symbol("6472.JP") == "6472.T"


def test_to_yahoo_symbol_dot_jt_suffix():
    assert to_yahoo_symbol("6472.JT") == "6472.T"


def test_to_yahoo_symbol_us_ticker_is_none():
    assert to_yahoo_symbol("AAPL") is None


def test_to_yahoo_symbol_empty_is_none():
    assert to_yahoo_symbol("") is None


def test_to_yahoo_symbol_strips_whitespace():
    assert to_yahoo_symbol("  6472.T  ") == "6472.T"


def test_to_yahoo_symbol_full_width_digits():
    assert to_yahoo_symbol("６４７２") == "6472.T"


def test_to_yahoo_symbol_full_width_with_suffix():
    assert to_yahoo_symbol("　６４７２．Ｔ　") == "6472.T"


def test_to_yahoo_symbol_non_digit_only_is_none():
    assert to_yahoo_symbol(".T") is None


# --- parse_chart_json ---


def _chart_json(price=432.5, prev=439.7, ts=1750291200, currency="JPY"):
    """Yahoo chart API レスポンス相当の JSON 文字列を組み立てる。

    ts=1750291200 は 2025-06-19 09:00 JST 相当（テストでは as_of 日付の検証に使う）。
    """
    return json.dumps(
        {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "regularMarketPrice": price,
                            "chartPreviousClose": prev,
                            "regularMarketTime": ts,
                            "currency": currency,
                        }
                    }
                ],
                "error": None,
            }
        }
    )


def test_parse_chart_json_normal():
    out = parse_chart_json(_chart_json())
    assert out["price"] == pytest.approx(432.5)
    assert out["change"] == pytest.approx(432.5 - 439.7)
    assert out["change_pct"] == pytest.approx((432.5 - 439.7) / 439.7 * 100)


def test_parse_chart_json_as_of_is_jst_date():
    # epoch 1750291200 = 2025-06-19 00:00 UTC = 2025-06-19 09:00 JST
    out = parse_chart_json(_chart_json(ts=1750291200))
    assert out["as_of"] == "2025-06-19"


def test_parse_chart_json_as_of_jst_crosses_date_boundary():
    # epoch 1750255200 = 2025-06-18 14:00 UTC = 2025-06-18 23:00 JST（同日）
    # epoch 1750258800 = 2025-06-18 15:00 UTC = 2025-06-19 00:00 JST（翌日に繰り上がる）
    assert parse_chart_json(_chart_json(ts=1750258800))["as_of"] == "2025-06-19"


def test_parse_chart_json_error_non_null_is_none():
    payload = json.dumps(
        {"chart": {"result": None, "error": {"code": "Not Found"}}}
    )
    assert parse_chart_json(payload) is None


def test_parse_chart_json_result_missing_is_none():
    payload = json.dumps({"chart": {"result": None, "error": None}})
    assert parse_chart_json(payload) is None


def test_parse_chart_json_result_empty_list_is_none():
    payload = json.dumps({"chart": {"result": [], "error": None}})
    assert parse_chart_json(payload) is None


def test_parse_chart_json_price_null_is_none():
    payload = _chart_json()
    obj = json.loads(payload)
    obj["chart"]["result"][0]["meta"]["regularMarketPrice"] = None
    assert parse_chart_json(json.dumps(obj)) is None


def test_parse_chart_json_prev_null_is_none():
    payload = _chart_json()
    obj = json.loads(payload)
    obj["chart"]["result"][0]["meta"]["chartPreviousClose"] = None
    assert parse_chart_json(json.dumps(obj)) is None


def test_parse_chart_json_price_non_numeric_is_none():
    payload = _chart_json()
    obj = json.loads(payload)
    obj["chart"]["result"][0]["meta"]["regularMarketPrice"] = "N/A"
    assert parse_chart_json(json.dumps(obj)) is None


def test_parse_chart_json_broken_json_is_none():
    assert parse_chart_json("{not valid json") is None


def test_parse_chart_json_empty_is_none():
    assert parse_chart_json("") is None


# --- compute_change ---


def test_compute_change_up():
    change, pct = compute_change(2700.0, 2750.0)
    assert change == pytest.approx(50.0)
    assert pct == pytest.approx(50.0 / 2700.0 * 100)


def test_compute_change_down():
    change, pct = compute_change(2700.0, 2650.0)
    assert change == pytest.approx(-50.0)
    assert pct == pytest.approx(-50.0 / 2700.0 * 100)


def test_compute_change_prev_zero_guard():
    change, pct = compute_change(0.0, 2750.0)
    assert pct == 0.0


def test_compute_change_prev_negative_guard():
    change, pct = compute_change(-1.0, 2750.0)
    assert pct == 0.0


# --- enrich_stock_prices ---


def _quote(price, change, pct, as_of="2026-06-18"):
    return {"price": price, "change": change, "change_pct": pct, "as_of": as_of}


def test_enrich_all_success_merges_keys():
    picks = [{"ticker": "6472", "name": "NTN"}]

    def fake_fetcher(symbol, *, timeout=10.0):
        assert symbol == "6472.T"
        return _quote(432.0, -7.2, -1.6)

    out = enrich_stock_prices(picks, fetcher=fake_fetcher)
    assert out[0]["price"] == 432.0
    assert out[0]["change"] == -7.2
    assert out[0]["change_pct"] == -1.6
    assert out[0]["as_of"] == "2026-06-18"
    assert out[0]["yahoo_symbol"] == "6472.T"
    # 元のキーは保持
    assert out[0]["name"] == "NTN"


def test_enrich_fetcher_none_no_price_keys():
    picks = [{"ticker": "6472", "name": "NTN"}]

    def fake_fetcher(symbol, *, timeout=10.0):
        return None

    out = enrich_stock_prices(picks, fetcher=fake_fetcher)
    assert "price" not in out[0]
    assert "yahoo_symbol" not in out[0]


def test_enrich_fetcher_raises_returns_original():
    picks = [{"ticker": "6472", "name": "NTN"}]

    def fake_fetcher(symbol, *, timeout=10.0):
        raise RuntimeError("boom")

    out = enrich_stock_prices(picks, fetcher=fake_fetcher)
    assert out[0]["name"] == "NTN"
    assert "price" not in out[0]


def test_enrich_us_ticker_skipped():
    picks = [{"ticker": "AAPL", "name": "Apple"}]
    called = []

    def fake_fetcher(symbol, *, timeout=10.0):
        called.append(symbol)
        return _quote(100.0, 1.0, 1.0)

    out = enrich_stock_prices(picks, fetcher=fake_fetcher)
    assert called == []  # symbol が取れないので fetcher を呼ばない
    assert "price" not in out[0]


def test_enrich_empty_list():
    assert enrich_stock_prices([]) == []


def test_enrich_returns_input_on_unexpected_error():
    # stock_picks が dict でない要素を含んでも全体は壊れず元を返す
    picks = ["not a dict"]
    out = enrich_stock_prices(picks, fetcher=lambda s, *, timeout=10.0: None)
    assert out == picks
