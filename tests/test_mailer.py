import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mailer import _build_text, _build_html  # noqa: E402


def _item_full():
    return {
        "category": "国内ビジネス",
        "title": "テスト記事",
        "summary": "これは要約です。",
        "background": "これは背景の説明です。",
        "companies": [
            {"name": "テスト電機", "description": "家電を作る会社です。"},
        ],
        "people": [
            {"name": "山田太郎", "description": "テスト電機の社長です。"},
        ],
        "keywords": [
            {"word": "インフレ", "note": "物価が上がること"},
            {"word": "金利", "note": "お金を借りる時のコスト"},
        ],
        "url": "https://example.com/a",
        "source": "テスト新聞",
    }


def _item_legacy():
    # 旧キャッシュ相当（新フィールドなし・記事ごと life_impact あり）
    return {
        "category": "国際",
        "title": "旧記事",
        "summary": "旧要約。",
        "life_impact": "旧・記事ごとの生活影響テキスト",
        "url": "https://example.com/b",
        "source": "旧新聞",
    }


# --- text ---


def test_build_text_includes_new_fields():
    result = {"summaries": [_item_full()], "stock_picks": []}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "これは背景の説明です。" in text
    assert "テスト電機" in text
    assert "家電を作る会社です。" in text
    assert "山田太郎" in text
    assert "テスト電機の社長です。" in text
    assert "インフレ" in text
    assert "物価が上がること" in text


def test_build_text_global_life_impact_rendered():
    result = {
        "summaries": [_item_full()],
        "life_impact": "全体の生活への影響テキスト",
        "stock_picks": [],
    }
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "全体の生活への影響テキスト" in text


def test_build_text_companies_people_empty_no_block():
    item = _item_full()
    item["companies"] = []
    item["people"] = []
    result = {"summaries": [item], "stock_picks": []}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "🏢" not in text
    assert "👤" not in text


def test_build_text_no_global_terms():
    # 旧トップレベル terms は出力されないこと
    result = {
        "summaries": [_item_full()],
        "terms": [{"word": "X", "reading": "えっくす", "explanation": "説明"}],
        "life_impact": "全体の生活への影響テキスト",
        "stock_picks": [],
    }
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "今日の用語" not in text


def test_build_text_legacy_no_exception_and_no_article_life_impact():
    result = {"summaries": [_item_legacy()]}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "旧要約。" in text
    # 旧・記事ごとの life_impact は描画されない
    assert "旧・記事ごとの生活影響テキスト" not in text


# --- html ---


def test_build_html_includes_new_fields():
    result = {"summaries": [_item_full()], "stock_picks": []}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert "これは背景の説明です。" in html_out
    assert "テスト電機" in html_out
    assert "家電を作る会社です。" in html_out
    assert "山田太郎" in html_out
    assert "テスト電機の社長です。" in html_out
    assert "インフレ" in html_out
    assert "物価が上がること" in html_out


def test_build_html_global_life_impact_rendered():
    result = {
        "summaries": [_item_full()],
        "life_impact": "全体の生活への影響テキスト",
        "stock_picks": [],
    }
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert "全体の生活への影響テキスト" in html_out


def test_build_html_companies_people_empty_no_block():
    item = _item_full()
    item["companies"] = []
    item["people"] = []
    result = {"summaries": [item], "stock_picks": []}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert "🏢" not in html_out
    assert "👤" not in html_out


def test_build_html_no_global_terms():
    result = {
        "summaries": [_item_full()],
        "terms": [{"word": "X", "reading": "えっくす", "explanation": "説明"}],
        "life_impact": "全体の生活への影響テキスト",
        "stock_picks": [],
    }
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert "今日の用語" not in html_out


def test_build_html_legacy_no_exception_and_no_article_life_impact():
    result = {"summaries": [_item_legacy()]}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert "旧要約。" in html_out
    assert "旧・記事ごとの生活影響テキスト" not in html_out


def test_build_html_escapes_script_in_new_fields():
    item = _item_full()
    item["background"] = "<script>alert(1)</script>"
    item["keywords"] = [{"word": "<b>x</b>", "note": "<i>note</i>"}]
    item["companies"] = [{"name": "<b>co</b>", "description": "<script>c</script>"}]
    item["people"] = [{"name": "<b>p</b>", "description": "<script>p</script>"}]
    result = {"summaries": [item], "stock_picks": []}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert "<script>alert(1)</script>" not in html_out
    assert "&lt;script&gt;" in html_out
    assert "<b>x</b>" not in html_out
    assert "&lt;b&gt;" in html_out
    assert "<b>co</b>" not in html_out
    assert "<script>c</script>" not in html_out
    assert "<script>p</script>" not in html_out
