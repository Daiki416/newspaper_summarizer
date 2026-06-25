# このファイルは J-Quants（日本取引所グループ提供の API）の銘柄マスタを使って、
# 「社名 → 証券コード（Yahoo シンボル）」を権威的に解決するためのモジュールです。
#
# 背景: Claude(LLM) は証券コードを記憶から想起するため、実在しない誤コードを
# 出すことがある（例: U-NEXT HOLDINGS の正しい 9418 ではなく 9958）。
# そこで LLM の暗記に頼らず、J-Quants 銘柄マスタで社名からコードを引く。
#
# 設計方針（quotes.py の作法に合わせる）:
#   - urlopen には必ず timeout を渡す
#   - ネットワーク/パース失敗は raise せず None を返す。ログは type(e).__name__ のみ
#   - 秘密情報（JQUANTS_API_KEY）は print/例外/戻り値に一切出さない
#
# J-Quants V2 仕様（実 API で確認済み）:
#   - 認証: HTTP ヘッダー `x-api-key: <APIキー>`（恒久キー）
#   - GET https://api.jquants.com/v2/equities/master（無料プランで約4449銘柄）
#   - レスポンス: {"data":[{"Code":"94180"(5桁文字列),
#                          "CoName":"Ｕ−ＮＥＸＴ　ＨＯＬＤＩＮＧＳ"(全角),
#                          "CoNameEn":"U-NEXT HOLDINGS Co.,Ltd.", ...}]}
#   - コードは5桁。Yahoo 用は先頭4桁 → "9418.T"。CoName は全角なので NFKC 必須。

import json
import os
import re
import unicodedata
import urllib.request

# J-Quants 銘柄マスタのエンドポイント（V2）。
_MASTER_URL = "https://api.jquants.com/v2/equities/master"

# resp.read() の読み取り上限（理論的メモリ枯渇ガード）。
# 銘柄マスタは約4449件で数MB級になり得るため quotes.py の 1MB より大きめにする。
_MAX_BYTES = 16_000_000

# 5桁コードのうち先頭4桁が全数字のときだけ Yahoo シンボルにする。
# 英数字新形式（"130A0" 等）は先頭4桁に英字が混じるため除外（安全側）。
_NUMERIC4_RE = re.compile(r"^[0-9]{4}$")

# normalize_company_name で除去する社名接尾辞（正規化後＝小文字・記号除去前に判定するため、
# ここでは正規化と同じ前処理を施した上で比較する）。語尾から除去する。
_SUFFIXES = (
    "株式会社",
    "(株)",
    "co.,ltd.",
    "co.ltd.",
    "coltd",
    "ltd.",
    "ltd",
    "inc.",
    "inc",
    "corporation",
    "corp.",
    "corp",
    "company",
    "co.",
    "co",
    "holdings",
    "holding",
)

# NFKC では ASCII 化されない各種ダッシュ/マイナス（U+2212 等）を ASCII ハイフンへ
# 寄せるための変換表。これにより全角社名と英語名のキーが一致する。
_DASH_CHARS = "‐‑‒–—―−－"
_DASH_TABLE = {ord(c): "-" for c in _DASH_CHARS}

# 照合キーから除去する記号・空白（NFKC 後）。英数字と日本語だけを残す方針。
_NON_KEY_RE = re.compile(r"[\s\-‐―—–_.,，、・（）()&'\"]+")

# プロセス内キャッシュ。get_name_index() が初回のみ構築し以後再利用する。
_name_index_cache: dict | None = None
_name_index_loaded = False


# 接尾辞の前後にまとわりつく区切り文字（空白・句読点・引用符・ハイフン）。
# 接尾辞の判定前後で都度トリムするために使う。
_TRIM_CHARS = " .,-_’'\""


def _strip_trailing_suffixes(text: str) -> str:
    """語尾の社名接尾辞（_SUFFIXES）を繰り返し除去して返す。

    接尾辞の前後にある空白・記号は都度トリムする。
    例: "u-next holdings co.,ltd." → "u-next"。
    どの接尾辞にも一致しなくなった時点で確定する。
    """
    text = text.rstrip(_TRIM_CHARS)
    while True:
        for suffix in _SUFFIXES:
            if text.endswith(suffix):
                # 接尾辞を1つ落とし、残った末尾の区切り文字もトリムして次の周回へ。
                text = text[: -len(suffix)].rstrip(_TRIM_CHARS)
                break
        else:
            # どの接尾辞にも一致しなければ確定。
            return text


def normalize_company_name(s: str) -> str:
    """社名を照合キーへ正規化する。

    手順: NFKC 正規化 → 小文字化 → 接尾辞（株式会社/(株)/co.,ltd./inc./
    corporation/holdings 等）除去 → 空白・記号除去。
    例: "Ｕ−ＮＥＸＴ　ＨＯＬＤＩＮＧＳ"（全角）と "U-NEXT HOLDINGS Co.,Ltd."
    が同一キーになる。
    """
    if not s:
        return ""
    # NFKC で全角→半角・互換文字を統一し、小文字化する。
    text = unicodedata.normalize("NFKC", s).lower().strip()
    # NFKC で残るダッシュ/マイナス類を ASCII ハイフンへ寄せる
    # （全角社名 "Ｕ−ＮＥＸＴ" と英語 "U-NEXT" のキーを一致させるため）。
    text = text.translate(_DASH_TABLE)
    # 接尾辞を語尾から繰り返し除去する（"... co.,ltd." → "..."）。
    text = _strip_trailing_suffixes(text)
    # 残った空白・記号を全て除去して照合キーにする。
    return _NON_KEY_RE.sub("", text)


def code_to_yahoo_symbol(code: str) -> str | None:
    """J-Quants の5桁コードを Yahoo シンボル "{4桁}.T" に変換する。

    "94180" → "9418.T"。先頭4桁が全数字のときのみ採用する。
    英数字新形式（"130A0" 等）は先頭4桁に英字が混じるため None（除外＝安全側）。
    二重 ".T" は作らない。
    """
    if not code:
        return None
    head = code[:4]
    if not _NUMERIC4_RE.match(head):
        return None
    return f"{head}.T"


def build_name_index(records: list) -> dict:
    """銘柄マスタの各レコードから {正規化社名キー: Yahoo シンボル} 辞書を作る。

    各レコードの CoName と CoNameEn の両方を normalize_company_name でキー化する。
    完全一致照合用。英数字コード（先頭4桁が非数字）のレコードは除外する。

    曖昧キー除外: 同一正規化キーに「異なる証券コード」が2つ以上ぶら下がる場合、
    そのキーは別法人の衝突（例: 接尾辞だけ異なる Resona Holdings と
    Resona Corporation）として誤解決を防ぐため index から完全に除外する。
    なお同一銘柄の CoName(全角) と CoNameEn(英語) は同じコードに解決されるので
    衝突ではなく、除外対象にならない（同一コードなら共存可）。
    """
    # 各キーにぶら下がる Yahoo シンボルの集合を集める（衝突検出のため）。
    key_to_symbols: dict[str, set[str]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        symbol = code_to_yahoo_symbol(str(record.get("Code", "")))
        if symbol is None:
            continue
        for name_field in ("CoName", "CoNameEn"):
            name = record.get(name_field)
            if not name:
                continue
            key = normalize_company_name(str(name))
            if key:
                key_to_symbols.setdefault(key, set()).add(symbol)
    # 異なるコードが同一キーに集まったキーは曖昧として除外し、
    # ただ1つのコードに一意解決できるキーのみ採用する。
    return {
        key: next(iter(symbols))
        for key, symbols in key_to_symbols.items()
        if len(symbols) == 1
    }


def resolve_company(name: str, index: dict) -> str | None:
    """社名を正規化し index の完全一致で Yahoo シンボルを返す。

    ヒットしなければ None。部分一致・あいまい一致は採用しない（誤解決防止）。
    """
    if not name:
        return None
    key = normalize_company_name(name)
    if not key:
        return None
    return index.get(key)


def fetch_master(timeout: float = 15.0) -> list | None:
    """J-Quants 銘柄マスタを取得し data 配列（list）を返す。

    認証は環境変数 JQUANTS_API_KEY を x-api-key ヘッダーに載せる。
    未設定 / ネットワーク失敗 / パース失敗は None を返す（raise しない）。
    例外は型名のみログし、API キーは絶対に出さない。
    """
    api_key = os.environ.get("JQUANTS_API_KEY")
    if not api_key:
        # キー未設定。秘密情報は無いので値も出さない。
        print("J-Quants: JQUANTS_API_KEY が未設定のため取得をスキップします")
        return None
    if not _MASTER_URL.startswith("https://"):
        print("J-Quants URL が https ではありません")
        return None
    try:
        req = urllib.request.Request(_MASTER_URL, headers={"x-api-key": api_key})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            # 読み取り上限を設けて理論的メモリ枯渇を防ぐ（マスタは数MB級）。
            raw = resp.read(_MAX_BYTES).decode("utf-8", errors="replace")
        data = json.loads(raw)
        records = data["data"]
    except Exception as e:
        # 秘密情報（API キー）は出さない。例外型名のみ。
        print(f"J-Quants 取得失敗: {type(e).__name__}")
        return None
    if not isinstance(records, list):
        print("J-Quants 応答が想定形式ではありません")
        return None
    return records


def get_name_index() -> dict | None:
    """{正規化社名キー: Yahoo シンボル} 辞書をプロセス内キャッシュ付きで返す。

    初回のみ fetch_master → build_name_index を実行し、以後は再利用する。
    キー未設定 / fetch 失敗時は None（呼び出し側で全件除外＝安全側に倒す）。
    """
    global _name_index_cache, _name_index_loaded
    if _name_index_loaded:
        return _name_index_cache
    records = fetch_master()
    if records is None:
        # 失敗時もロード済みフラグを立て、毎回の HTTP 再試行を避ける。
        _name_index_cache = None
        _name_index_loaded = True
        return None
    _name_index_cache = build_name_index(records)
    _name_index_loaded = True
    return _name_index_cache
