import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

import quotes  # noqa: E402
from quotes import (  # noqa: E402
    to_yahoo_symbol,
    parse_chart_json,
    compute_change,
    enrich_stock_prices,
    fetch_quote,
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


# --- _CODE_RE 厳密化境界（無効ティッカーは None） ---


def test_to_yahoo_symbol_five_digits_is_none():
    assert to_yahoo_symbol("12345") is None


def test_to_yahoo_symbol_trailing_letter_is_none():
    assert to_yahoo_symbol("6472X") is None


def test_to_yahoo_symbol_too_many_digits_is_none():
    assert to_yahoo_symbol("6472999") is None


def test_to_yahoo_symbol_underscore_suffix_is_none():
    # suffix は ASCII 英字のみ許容。"6472._" は \w の _ 許容を排除したため弾く
    assert to_yahoo_symbol("6472._") is None


def test_to_yahoo_symbol_digit_suffix_is_none():
    # suffix に数字は許さない（[A-Za-z]+ のみ）
    assert to_yahoo_symbol("6472.1") is None


# --- parse_chart_json ---


def _chart_json(price=432.5, prev=439.7, ts=1750291200):
    """Yahoo chart API レスポンス相当の JSON 文字列を組み立てる。

    ts=1750291200 は 2025-06-19 09:00 JST 相当（テストでは as_of 日付の検証に使う）。
    注: 本体 parse_chart_json は currency を読まない（JPY 以外の扱いは将来検討）ため、
    レスポンスにも currency は含めない。
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
    assert out["change_pct"] == pytest.approx((432.5 - 439.7) / 439.7 * 100)
    # change デッドフィールドはマージしない（戻り dict に含めない）
    assert "change" not in out


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


def test_enrich_multiple_picks_correspondence_preserved():
    # 並列化しても pick と quote の対応がズレないことを検証する。
    # 各シンボルに固有の price を返し、マージ先が一致するか確認する。
    picks = [
        {"ticker": "6472", "name": "NTN"},
        {"ticker": "7203", "name": "トヨタ"},
        {"ticker": "9984", "name": "SBG"},
    ]
    price_by_symbol = {"6472.T": 100.0, "7203.T": 200.0, "9984.T": 300.0}

    def fake_fetcher(symbol, *, timeout=10.0):
        return _quote(price_by_symbol[symbol], 0.0, 0.0)

    out = enrich_stock_prices(picks, fetcher=fake_fetcher)
    # 入力リストをそのまま返す（同一オブジェクト）
    assert out is picks
    assert out[0]["price"] == 100.0 and out[0]["yahoo_symbol"] == "6472.T"
    assert out[1]["price"] == 200.0 and out[1]["yahoo_symbol"] == "7203.T"
    assert out[2]["price"] == 300.0 and out[2]["yahoo_symbol"] == "9984.T"
    assert out[0]["name"] == "NTN"


def test_enrich_mixed_skip_and_success_correspondence():
    # スキップ対象（US ティッカー）が間に挟まっても他の pick がズレない
    picks = [
        {"ticker": "6472", "name": "NTN"},
        {"ticker": "AAPL", "name": "Apple"},
        {"ticker": "7203", "name": "トヨタ"},
    ]
    price_by_symbol = {"6472.T": 100.0, "7203.T": 200.0}

    def fake_fetcher(symbol, *, timeout=10.0):
        return _quote(price_by_symbol[symbol], 0.0, 0.0)

    out = enrich_stock_prices(picks, fetcher=fake_fetcher)
    assert out[0]["price"] == 100.0
    assert "price" not in out[1]  # AAPL はスキップ
    assert out[2]["price"] == 200.0


def test_enrich_empty_list():
    assert enrich_stock_prices([]) == []


def test_enrich_returns_input_on_unexpected_error():
    # stock_picks が dict でない要素を含んでも全体は壊れず元を返す
    picks = ["not a dict"]
    out = enrich_stock_prices(picks, fetcher=lambda s, *, timeout=10.0: None)
    assert out == picks


# --- fetch_quote（urlopen をパッチ・実 HTTP 不使用） ---


class _FakeResp:
    """urlopen が返すレスポンス相当。with 文と read() を提供する。"""

    def __init__(self, raw: bytes):
        self._raw = raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, amt=None):
        # fetch_quote は resp.read(_MAX_BYTES) で上限付き読み取りを行う。
        # テストレスポンスは小さいため amt の有無で結果は変わらない。
        return self._raw


def test_fetch_quote_sets_user_agent_and_timeout(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return _FakeResp(_chart_json().encode("utf-8"))

    monkeypatch.setattr(quotes.urllib.request, "urlopen", fake_urlopen)
    out = fetch_quote("6472.T", timeout=7.5)

    assert out is not None
    # UA ヘッダが Request に付与されている（urllib はヘッダ名を title-case 化する）
    assert captured["req"].get_header("User-agent") == "Mozilla/5.0"
    # urlopen に timeout が渡る
    assert captured["timeout"] == 7.5


def test_fetch_quote_decode_errors_replace(monkeypatch):
    # 不正バイト列でも errors="replace" でデコードし、後段 parse に進める
    valid = _chart_json().encode("utf-8")
    raw = valid + b"\xff\xfe"  # 末尾に不正バイトを付与（JSON 的には壊れる）

    def fake_urlopen(req, timeout=None):
        return _FakeResp(raw)

    monkeypatch.setattr(quotes.urllib.request, "urlopen", fake_urlopen)
    # デコード自体は例外を出さない（replace 経路）。壊れた JSON なので parse は None。
    assert fetch_quote("6472.T") is None


def test_fetch_quote_invalid_json_returns_none(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return _FakeResp(b"{not valid json")

    monkeypatch.setattr(quotes.urllib.request, "urlopen", fake_urlopen)
    assert fetch_quote("6472.T") is None


def test_fetch_quote_urlopen_raises_returns_none(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(quotes.urllib.request, "urlopen", fake_urlopen)
    assert fetch_quote("6472.T") is None


def test_fetch_quote_non_https_url_returns_none(monkeypatch):
    # _YAHOO_URL が将来 http:// 等へ改変された場合、urlopen を呼ばず None を返す
    monkeypatch.setattr(
        quotes, "_YAHOO_URL", "http://query1.finance.yahoo.com/v8/{symbol}"
    )

    def fake_urlopen(req, timeout=None):
        raise AssertionError("https でない URL で urlopen を呼んではいけない")

    monkeypatch.setattr(quotes.urllib.request, "urlopen", fake_urlopen)
    assert fetch_quote("6472.T") is None


def test_fetch_quote_caps_read_at_max_bytes(monkeypatch):
    # resp.read に _MAX_BYTES が上限として渡されることを検証する
    captured = {}

    class _CapResp:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self, amt=None):
            captured["amt"] = amt
            return _chart_json().encode("utf-8")

    def fake_urlopen(req, timeout=None):
        return _CapResp()

    monkeypatch.setattr(quotes.urllib.request, "urlopen", fake_urlopen)
    assert fetch_quote("6472.T") is not None
    assert captured["amt"] == quotes._MAX_BYTES
