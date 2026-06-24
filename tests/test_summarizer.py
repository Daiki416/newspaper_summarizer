import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from summarizer import _normalize_entity_fields  # noqa: E402


# --- keywords ---


def test_keywords_already_dict_list_kept():
    summaries = [{"keywords": [{"word": "インフレ", "note": "物価が上がること"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["keywords"] == [{"word": "インフレ", "note": "物価が上がること"}]


def test_keywords_str_elements_removed():
    # AIが ["インフレ", "金利"] のような str リストを返すケース
    summaries = [{"keywords": ["インフレ", "金利"]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["keywords"] == []


def test_keywords_mixed_elements_only_dict_kept():
    summaries = [{"keywords": ["インフレ", {"word": "金利", "note": "借入コスト"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["keywords"] == [{"word": "金利", "note": "借入コスト"}]


def test_keywords_as_json_string_repaired():
    summaries = [{"keywords": '[{"word": "円安", "note": "円の価値が下がる"}]'}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["keywords"] == [{"word": "円安", "note": "円の価値が下がる"}]


def test_keywords_missing_defaults_to_empty_list():
    summaries = [{}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["keywords"] == []


def test_non_dict_summary_item_skipped():
    # summaries の要素が非dict（str等）でもクラッシュしない
    summaries = ["不正な要素", {"keywords": [{"word": "金利", "note": "x"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0] == "不正な要素"
    assert summaries[1]["keywords"] == [{"word": "金利", "note": "x"}]


def test_keywords_non_list_non_str_reset_to_empty():
    summaries = [{"keywords": 123}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["keywords"] == []


# --- companies ---


def test_companies_already_dict_list_kept():
    summaries = [{"companies": [{"name": "A社", "description": "半導体メーカー"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["companies"] == [{"name": "A社", "description": "半導体メーカー"}]


def test_companies_str_elements_removed():
    summaries = [{"companies": ["A社", "B社"]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["companies"] == []


def test_companies_mixed_elements_only_dict_kept():
    summaries = [{"companies": ["A社", {"name": "B社", "description": "通信"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["companies"] == [{"name": "B社", "description": "通信"}]


def test_companies_as_json_string_repaired():
    summaries = [{"companies": '[{"name": "C社", "description": "鉄道"}]'}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["companies"] == [{"name": "C社", "description": "鉄道"}]


def test_companies_missing_defaults_to_empty_list():
    summaries = [{}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["companies"] == []


def test_companies_non_list_non_str_reset_to_empty():
    summaries = [{"companies": 123}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["companies"] == []


# --- people ---


def test_people_already_dict_list_kept():
    summaries = [{"people": [{"name": "山田太郎", "description": "首相"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["people"] == [{"name": "山田太郎", "description": "首相"}]


def test_people_str_elements_removed():
    summaries = [{"people": ["山田", "鈴木"]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["people"] == []


def test_people_mixed_elements_only_dict_kept():
    summaries = [{"people": ["山田", {"name": "鈴木", "description": "日銀総裁"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["people"] == [{"name": "鈴木", "description": "日銀総裁"}]


def test_people_as_json_string_repaired():
    summaries = [{"people": '[{"name": "佐藤", "description": "CEO"}]'}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["people"] == [{"name": "佐藤", "description": "CEO"}]


def test_people_missing_defaults_to_empty_list():
    summaries = [{}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["people"] == []


def test_people_non_list_non_str_reset_to_empty():
    summaries = [{"people": 123}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["people"] == []


def test_non_dict_item_skipped_for_all_fields():
    summaries = ["bad", {"keywords": [], "companies": [], "people": []}]
    _normalize_entity_fields(summaries)
    assert summaries[0] == "bad"
    assert summaries[1] == {"keywords": [], "companies": [], "people": []}


# --- 不正なstr（JSON配列でない素の文字列）→ [] フォールバック ---


def test_keywords_invalid_str_falls_back_to_empty():
    # repair_json("該当なし") -> '' となり json.loads('') が落ちるケースの回帰テスト
    summaries = [{"keywords": "該当なし"}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["keywords"] == []


def test_companies_invalid_str_falls_back_to_empty():
    summaries = [{"companies": "該当なし"}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["companies"] == []


def test_people_invalid_str_falls_back_to_empty():
    summaries = [{"people": "該当なし"}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["people"] == []


def test_keywords_empty_str_falls_back_to_empty():
    summaries = [{"keywords": ""}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["keywords"] == []


def test_companies_whitespace_str_falls_back_to_empty():
    summaries = [{"companies": "  "}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["companies"] == []


# --- dict要素内の非str値を str 化する ---


def test_companies_non_str_values_coerced_to_str():
    summaries = [{"companies": [{"name": 123, "description": "x"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["companies"] == [{"name": "123", "description": "x"}]


def test_keywords_non_str_values_coerced_to_str():
    summaries = [{"keywords": [{"word": 456, "note": "y"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["keywords"] == [{"word": "456", "note": "y"}]


def test_people_non_str_values_coerced_to_str():
    summaries = [{"people": [{"name": 789, "description": "z"}]}]
    _normalize_entity_fields(summaries)
    assert summaries[0]["people"] == [{"name": "789", "description": "z"}]
