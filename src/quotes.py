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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from typing import Callable

# Yahoo Finance chart API（日足。meta（現在値・前日終値）だけ使うので range=1d で十分）。
# 不変条件: ホストは query1.finance.yahoo.com 固定（query2 等へは切り替えない）。
_YAHOO_URL = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=1d"
)

# デフォルトの urllib User-Agent だと 404 になるため、ブラウザ風 UA を必ず付ける
_USER_AGENT = "Mozilla/5.0"

# resp.read() の読み取り上限（理論的メモリ枯渇ガード）。
# 正常な Yahoo chart レスポンスは数KB なので 1MB あれば十分。
_MAX_BYTES = 1_000_000

# enrich_stock_prices の並列度。stock_picks は最大3件のため。
_MAX_WORKERS = 3

# 4 桁の数字コード（任意で ".suffix" 付き）に厳密一致する正規表現。
# 両端アンカー + ASCII 限定。suffix は ASCII 英字のみ許容（[A-Za-z]+）。
# "6472" / "6472.T" / "6472.JP" / "6472.JT" は通り、
# "12345" / "6472X" / "6472999" / "6472._" / "6472.1" は一致しない
# （\w の Unicode・"_" 許容を排除。全角は NFKC で半角化済み）。
_CODE_RE = re.compile(r"^([0-9]{4})(?:\.[A-Za-z]+)?$")

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
        # price / prev は数値であること（None・文字列は失敗扱い）。
        # 同名再代入を避けて別名（*_num）に束ねる。
        price_num = float(price)
        prev_num = float(prev)
        as_of = datetime.fromtimestamp(int(ts), tz=_JST).strftime("%Y-%m-%d")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None

    # change（円額）は配信未使用のため破棄。change_pct のみ使う。
    _change, change_pct = compute_change(prev_num, price_num)
    return {
        "price": price_num,
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
    # _YAHOO_URL 将来改変への保険: スキームが https でなければ取得しない。
    # ベストエフォート方針に従い raise せず None を返す（配信を壊さない）。
    if not url.startswith("https://"):
        print(f"Yahoo URL が https ではありません: symbol={symbol}")
        return None
    try:
        # デフォルト UA だと 404 になるため User-Agent を付与する
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 読み取り上限を設けて理論的メモリ枯渇を防ぐ（正常レスポンスは数KB）
            json_text = resp.read(_MAX_BYTES).decode("utf-8", errors="replace")
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

    I/O バウンドのため ThreadPoolExecutor(max_workers=_MAX_WORKERS) で fetcher 呼び出しを並列化する。
    future を (pick, symbol) に対応づけてからマージするため、並列でも pick と quote の
    対応はズレない（マージ自体は呼び出しスレッドで in-place に行う）。
    """
    try:
        # symbol が取れる pick だけを (pick, symbol) として収集する。
        # 順序は入力順を保つ（in-place 更新なので結果順序は元リストのまま）。
        targets: list[tuple[dict, str]] = []
        for pick in stock_picks:
            try:
                symbol = to_yahoo_symbol(pick.get("ticker", ""))
            except Exception as e:
                print(f"株価マージ失敗: {type(e).__name__}")
                continue
            if symbol is None:
                continue
            targets.append((pick, symbol))

        if not targets:
            return stock_picks

        # fetcher 呼び出し（HTTP）のみ並列化する。各 future は (pick, symbol) に紐づく。
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            future_to_target = {
                executor.submit(fetcher, symbol, timeout=timeout): (pick, symbol)
                for pick, symbol in targets
            }
            # 完了順は不要なので as_completed は使わず登録順に result() を待つ
            for future in future_to_target:
                pick, symbol = future_to_target[future]
                try:
                    quote = future.result()
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
