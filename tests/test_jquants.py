import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from jquants import (  # noqa: E402
    normalize_company_name,
    code_to_yahoo_symbol,
    build_name_index,
    resolve_company,
)


# --- normalize_company_name ---


def test_normalize_full_width_and_english_same_key():
    # 全角 CoName と 英語 CoNameEn が同一キーに正規化される
    full = "Ｕ−ＮＥＸＴ　ＨＯＬＤＩＮＧＳ"  # noqa: RUF001
    en = "U-NEXT HOLDINGS Co.,Ltd."
    assert normalize_company_name(full) == normalize_company_name(en)


def test_normalize_removes_suffix_kabushiki_kaisha():
    assert normalize_company_name("トヨタ自動車株式会社") == normalize_company_name("トヨタ自動車")


def test_normalize_removes_inc_corporation():
    assert normalize_company_name("Sony Inc.") == normalize_company_name("Sony")
    assert normalize_company_name("Sony Corporation") == normalize_company_name("Sony")


def test_normalize_empty_string():
    assert normalize_company_name("") == ""


# --- code_to_yahoo_symbol ---


def test_code_to_yahoo_symbol_5digit():
    assert code_to_yahoo_symbol("94180") == "9418.T"


def test_code_to_yahoo_symbol_alnum_is_none():
    # 英数字新形式コード（130A0 等）は先頭4桁が全数字でないため除外（安全側）
    assert code_to_yahoo_symbol("130A0") is None


def test_code_to_yahoo_symbol_no_double_dot_t():
    # 二重 ".T" を作らない
    out = code_to_yahoo_symbol("72030")
    assert out == "7203.T"
    assert out.count(".T") == 1


# --- build_name_index + resolve_company ---


def _records():
    return [
        {
            "Code": "94180",
            "CoName": "Ｕ−ＮＥＸＴ　ＨＯＬＤＩＮＧＳ",  # noqa: RUF001
            "CoNameEn": "U-NEXT HOLDINGS Co.,Ltd.",
            "MktNm": "プライム",
        },
        {
            "Code": "72030",
            "CoName": "トヨタ自動車",
            "CoNameEn": "TOYOTA MOTOR CORPORATION",
            "MktNm": "プライム",
        },
        {
            # 英数字コードは除外される
            "Code": "130A0",
            "CoName": "新興テック",
            "CoNameEn": "Shinko Tech Inc.",
            "MktNm": "グロース",
        },
    ]


def test_build_name_index_resolves_by_coname():
    index = build_name_index(_records())
    assert resolve_company("Ｕ−ＮＥＸＴ　ＨＯＬＤＩＮＧＳ", index) == "9418.T"  # noqa: RUF001


def test_build_name_index_resolves_by_coname_en():
    index = build_name_index(_records())
    assert resolve_company("U-NEXT HOLDINGS Co.,Ltd.", index) == "9418.T"


def test_resolve_company_different_input_form():
    index = build_name_index(_records())
    # 別表記でも正規化キーが一致すれば解決する
    assert resolve_company("U-NEXT HOLDINGS", index) == "9418.T"


def test_resolve_company_unregistered_returns_none():
    index = build_name_index(_records())
    # ズレた社名は完全一致しない → None（部分一致・あいまい一致は不採用）
    assert resolve_company("USEN-NEXT HOLDINGS", index) is None


def test_build_name_index_excludes_alnum_code():
    index = build_name_index(_records())
    # 英数字コードのレコードは index に乗らない
    assert resolve_company("新興テック", index) is None
    assert resolve_company("Shinko Tech Inc.", index) is None


def test_resolve_company_empty_name_none():
    index = build_name_index(_records())
    assert resolve_company("", index) is None


# --- 曖昧キー除外（接尾辞だけ異なる別2法人の衝突）---


def test_colliding_key_different_codes_excluded():
    # 接尾辞だけが異なる別2法人が同一正規化キーに潰れる場合、
    # そのキーは曖昧として両方除外する（誤解決防止＝解決不可）。
    records = [
        {"Code": "10000", "CoName": "Resona Holdings", "CoNameEn": "Resona Holdings"},
        {"Code": "20000", "CoName": "Resona Corporation", "CoNameEn": "Resona Corporation"},
    ]
    index = build_name_index(records)
    assert resolve_company("Resona", index) is None
    assert resolve_company("Resona Holdings", index) is None
    assert resolve_company("Resona Corporation", index) is None


def test_same_code_coname_and_en_not_excluded_as_collision():
    # 同一銘柄の CoName(全角) と CoNameEn(英語) は同じコードに解決されるので
    # 衝突ではない（同一コードなら曖昧除外しない）。
    records = [
        {
            "Code": "94180",
            "CoName": "Ｕ−ＮＥＸＴ　ＨＯＬＤＩＮＧＳ",  # noqa: RUF001
            "CoNameEn": "U-NEXT HOLDINGS Co.,Ltd.",
        },
    ]
    index = build_name_index(records)
    assert resolve_company("Ｕ−ＮＥＸＴ　ＨＯＬＤＩＮＧＳ", index) == "9418.T"  # noqa: RUF001
    assert resolve_company("U-NEXT HOLDINGS Co.,Ltd.", index) == "9418.T"


def test_three_way_collision_all_excluded():
    # 3法人以上が同一キーに潰れる場合も全部除外する。
    records = [
        {"Code": "10000", "CoName": "Apex Holdings", "CoNameEn": "Apex Holdings"},
        {"Code": "20000", "CoName": "Apex Corporation", "CoNameEn": "Apex Corporation"},
        {"Code": "30000", "CoName": "Apex Inc.", "CoNameEn": "Apex Inc."},
    ]
    index = build_name_index(records)
    assert resolve_company("Apex", index) is None
