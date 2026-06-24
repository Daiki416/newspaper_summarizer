# このファイルは Yahoo Finance chart API から国内個別株の「現在値・前日比」を
# ベストエフォートで取得し、Claude が選んだ stock_picks にマージするためのモジュールです。
# チャートは扱いません。1 銘柄あたり 1 リクエスト（リトライ・並列・キャッシュなし）。
#
# 設計方針（storage.py の作法に合わせる）:
#   - urlopen には必ず timeout を渡す
#   - ネットワーク/パース失敗は raise せず None を返す。ログは type(e).__name__ のみ
#   - enrich_stock_prices は何があっても入力リストを返し、配信を壊さない
#   - 秘密情報は扱わない（URL/シンボルはログに出してよい）
#
# 補足: Stooq が JS ボット壁を導入しプレーン HTTP では取得不可になったため、
# JSON で現在値＋前日終値を 1 リクエストで返せる Yahoo chart API へ切り替えた。

import json
import re
import unicodedata
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Callable

# Yahoo Finance chart API（日足。meta（現在値・前日終値）だけ使うので range=1d で十分）。
# 不変条件: ホストは query1.finance.yahoo.com 固定（query2 等へは切り替えない）。
_YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
)

# デフォルトの urllib User-Agent だと 404 になるため、ブラウザ風 UA を必ず付ける
_USER_AGENT = "Mozilla/5.0"

# 4 桁の数字コード（任意で ".suffix" 付き）に厳密一致する正規表現。
# 両端アンカー + ASCII 限定。"6472" / "6472.T" / "6472.JP" は通り、
# "12345" / "6472X" / "6472999" は一致しない（全角は NFKC で半角化済み）。
_CODE_RE = re.compile(r"^([0-9]{4})(?:\.\w+)?$")

# 日本標準時（UTC+9）。as_of の日付変換に使う
_JST = timezone(timedelta(hours=9))


def to_yahoo_symbol(ticker: str) -> str | None:
    """日本株ティッカーを Yahoo シンボル "{code}.T" に正規化する。

    "6472" / "6472.T" / "6472.JP" / "6472.JT" → "6472.T"
    前後空白・全角は吸収し、4 桁数字コードを抽出する。
    4 桁コードを抽出できない（米国株 "AAPL" 等）/ 空文字 → None。
    """
    if not ticker:
        return None
    # 全角→半角などの正規化（全角数字 "６４７２" → "6472" 等）
    normalized = unicodedata.normalize("NFKC", ticker).strip()
    match = _CODE_RE.match(normalized)
    if not match:
        return None
    return f"{match.group(1)}.T"


def compute_change(prev_close: float, last_price: float) -> tuple[float, float]:
    """(change, change_pct) を返す。change = last - prev。

    prev_close <= 0 はゼロ除算ガードとして change_pct=0.0 を返す。
    """
    change = last_price - prev_close
    if prev_close <= 0:
        return (change, 0.0)
    change_pct = change / prev_close * 100
    return (change, change_pct)


def parse_chart_json(json_text: str) -> dict | None:
    """Yahoo chart API のレスポンス文字列をパースし現在値・前日比を返す。

    戻り: {"price", "change_pct", "as_of"} or None。
    price = meta["regularMarketPrice"], prev = meta["chartPreviousClose"]。
    as_of は meta["regularMarketTime"]（epoch 秒）を JST 日付 "YYYY-MM-DD" に変換。

    error 非 null / result 欠落・空 / price or prev が None・非数値 /
    JSON 壊れ → None（raise しない）。
    """
    if not json_text:
        return None
    try:
        data = json.loads(json_text)
        chart = data["chart"]
        # error が非 null なら取得失敗扱い
        if chart.get("error") is not None:
            return None
        result = chart.get("result")
        if not result:  # None / 空リスト
            return None
        meta = result[0]["meta"]
        price = meta["regularMarketPrice"]
        prev = meta["chartPreviousClose"]
        ts = meta["regularMarketTime"]
        # price / prev は数値であること（None・文字列は失敗扱い）
        price = float(price)
        prev = float(prev)
        as_of = datetime.fromtimestamp(int(ts), tz=_JST).strftime("%Y-%m-%d")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    # change（前日比の円額）は配信で未使用のデッドフィールドのためマージしない。
    # compute_change は change_pct 算出のために (change, change_pct) を返すが change は捨てる。
    _change, change_pct = compute_change(prev, price)
    return {
        "price": price,
        "change_pct": float(change_pct),
        "as_of": as_of,
    }


def fetch_quote(symbol: str, *, timeout: float = 10.0) -> dict | None:
    """Yahoo chart API から symbol の現在値・前日比を返す。

    戻り: {"price", "change_pct", "as_of"} or None。
    例外・タイムアウト・HTTPError・空/壊れレスポンスは全てここで握りつぶし
    None を返す（raise しない）。
    """
    url = _YAHOO_URL.format(symbol=symbol)
    try:
        # デフォルト UA だと 404 になるため User-Agent を付与する
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            json_text = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        # 秘密情報は出さない。例外型名のみ（URL/シンボルは出してよい）
        print(f"Yahoo 取得失敗: symbol={symbol} {type(e).__name__}")
        return None

    parsed = parse_chart_json(json_text)
    if parsed is None:
        print(f"Yahoo パース失敗: symbol={symbol}")
        return None
    return parsed


def enrich_stock_prices(
    stock_picks: list[dict],
    fetcher: Callable[..., dict | None] = fetch_quote,
    timeout: float = 10.0,
) -> list[dict]:
    """各 stock_pick に現在値・前日比をベストエフォートでマージして返す。

    fetcher はテスト差し替え点（既定は fetch_quote。テストでは実 HTTP を避けるため
    fetcher(symbol, timeout=...) を満たすスタブを渡す）。

    - to_yahoo_symbol(pick["ticker"]) が None ならスキップ（価格キーを付けない）
    - symbol が取れたら fetcher(symbol, timeout=timeout) を呼び結果を pick にマージ
    - fetcher が None / 例外 のときはその pick に価格キーを付けない（元のまま）
    - 全体を try/except で囲み、何があっても stock_picks をそのまま返す
    """
    try:
        for pick in stock_picks:
            try:
                symbol = to_yahoo_symbol(pick.get("ticker", ""))
                if symbol is None:
                    continue
                quote = fetcher(symbol, timeout=timeout)
                if quote is None:
                    continue
                pick.update(quote)
                pick["yahoo_symbol"] = symbol
            except Exception as e:
                # 個別 pick の失敗は他に波及させない
                print(f"株価マージ失敗: {type(e).__name__}")
                continue
    except Exception as e:
        # 何があっても配信を壊さない
        print(f"株価マージ全体失敗: {type(e).__name__}")
    return stock_picks
