import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mailer import (  # noqa: E402
    _build_text,
    _build_html,
    _format_price_line,
    _ENTITY_SECTIONS,
)


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


# --- stock_picks 現在値・前日比 ---


def _pick(**overrides):
    # ticker は J-Quants 解決へ移行し mailer 表示からは削除した（社名＋方向のみ）。
    base = {
        "name": "トヨタ",
        "direction": "↑",
        "reason": "好決算のため",
        "source_headline": "トヨタ過去最高益",
    }
    base.update(overrides)
    return base


def test_build_text_stock_meta_has_no_ticker():
    # stock-meta 行は社名＋方向のみ。証券コード（ticker）は表示しない。
    pick = _pick(ticker="7203")
    result = {"summaries": [], "stock_picks": [pick]}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "トヨタ" in text
    assert "↑" in text
    assert "7203" not in text


def test_build_html_stock_meta_has_no_ticker():
    pick = _pick(ticker="7203")
    result = {"summaries": [], "stock_picks": [pick]}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert "トヨタ" in html_out
    assert "7203" not in html_out


def test_build_text_stock_price_up():
    pick = _pick(price=2750.0, change=49.5, change_pct=1.8)
    result = {"summaries": [], "stock_picks": [pick]}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "現在値 2,750円（前日比 +1.8%）" in text


def test_build_text_stock_price_down():
    pick = _pick(price=2650.0, change=-50.0, change_pct=-0.5)
    result = {"summaries": [], "stock_picks": [pick]}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "現在値 2,650円（前日比 -0.5%）" in text


def test_build_text_stock_price_zero():
    pick = _pick(price=2700.0, change=0.0, change_pct=0.0)
    result = {"summaries": [], "stock_picks": [pick]}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "現在値 2,700円（前日比 ±0.0%）" in text


def test_build_text_no_price_no_line():
    # 価格キーが無い従来 pick では現在値行を出さない
    result = {"summaries": [], "stock_picks": [_pick()]}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "現在値" not in text
    # 既存の項目は従来通り表示される
    assert "好決算のため" in text
    assert "根拠: トヨタ過去最高益" in text


def test_build_html_stock_price_up():
    pick = _pick(price=2750.0, change=49.5, change_pct=1.8)
    result = {"summaries": [], "stock_picks": [pick]}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert 'class="stock-price"' in html_out
    assert "現在値 2,750円（前日比 +1.8%）" in html_out


def test_build_html_no_price_no_line():
    result = {"summaries": [], "stock_picks": [_pick()]}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert 'class="stock-price"' not in html_out
    assert "現在値" not in html_out


# --- _format_price_line ゼロ近傍境界（±0.0% 是正） ---


def test_format_price_line_near_zero_negative_shows_pm_zero():
    # -0.04% は四捨五入で -0.0% になってしまうため ±0.0% に是正する
    line = _format_price_line(_pick(price=2700.0, change_pct=-0.04))
    assert "（前日比 ±0.0%）" in line
    assert "-0.0%" not in line


def test_format_price_line_near_zero_positive_shows_pm_zero():
    # +0.04% も四捨五入で +0.0% になるため ±0.0% に是正する
    line = _format_price_line(_pick(price=2700.0, change_pct=0.04))
    assert "（前日比 ±0.0%）" in line
    assert "+0.0%" not in line


def test_build_text_pick_without_change_key_renders():
    # change デッドフィールドが無い pick でも問題なく描画される
    pick = _pick(price=2750.0, change_pct=1.8)
    assert "change" not in pick
    result = {"summaries": [], "stock_picks": [pick]}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "現在値 2,750円（前日比 +1.8%）" in text
    assert "根拠: トヨタ過去最高益" in text


def test_build_text_missing_required_keys_no_keyerror():
    # title/summary/url/source など必須キーが欠落しても KeyError で落ちず空文字で描画される
    result = {"summaries": [{"category": "国際"}], "stock_picks": []}
    text = _build_text("朝刊", result, "2026年6月23日")
    # クラッシュせず見出し（カテゴリ）は出る
    assert "国際" in text


def test_build_html_missing_required_keys_no_keyerror():
    result = {"summaries": [{"category": "国際"}], "stock_picks": []}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert "国際" in html_out


def test_build_text_stock_missing_keys_no_keyerror():
    # stock_picks 要素の必須キーが欠落しても KeyError で落ちない
    result = {"summaries": [], "stock_picks": [{}]}
    text = _build_text("朝刊", result, "2026年6月23日")
    assert "注目銘柄候補" in text


def test_build_html_stock_missing_keys_no_keyerror():
    result = {"summaries": [], "stock_picks": [{}]}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    assert "注目銘柄候補" in html_out


# --- stock_picks 描画の項目順固定（回帰） ---


def test_build_text_stock_item_order_fixed():
    # text 版: name/direction → reason → price_line → 根拠 の順で出現する
    pick = _pick(price=2750.0, change_pct=1.8)
    result = {"summaries": [], "stock_picks": [pick]}
    text = _build_text("朝刊", result, "2026年6月23日")
    i_meta = text.index("トヨタ")
    i_reason = text.index("好決算のため")
    i_price = text.index("現在値 2,750円（前日比 +1.8%）")
    i_basis = text.index("根拠: トヨタ過去最高益")
    assert i_meta < i_reason < i_price < i_basis


def test_build_html_stock_item_order_fixed():
    # html 版: stock-meta → reason → stock-price → 根拠 の順で出現する
    pick = _pick(price=2750.0, change_pct=1.8)
    result = {"summaries": [], "stock_picks": [pick]}
    html_out = _build_html("朝刊", result, "2026年6月23日")
    i_meta = html_out.index('class="stock-meta"')
    i_reason = html_out.index("好決算のため")
    i_price = html_out.index('class="stock-price"')
    i_basis = html_out.index("根拠: トヨタ過去最高益")
    assert i_meta < i_reason < i_price < i_basis


def test_entity_section_css_classes_defined_in_style_block():
    # _ENTITY_SECTIONS に書かれた CSS クラス名が <style> ブロックに必ず存在することを検証する。
    # 片方だけ改名すると CSS が無言で外れる乖離を、このテストで検知する。
    html_out = _build_html("朝刊", {"summaries": []}, "2026年6月23日")
    start = html_out.index("<style>")
    end = html_out.index("</style>")
    style_block = html_out[start:end]
    for section in _ENTITY_SECTIONS:
        for css_key in ("wrapper_css", "item_css", "name_css"):
            cls = section[css_key]
            assert (
                f".{cls}" in style_block
            ), f"CSS クラス .{cls}（{section['field']} の {css_key}）が <style> に定義されていません"


def test_style_block_entity_classes_all_defined_in_entity_sections():
    # 逆方向整合: <style> 内のエンティティ用クラスに _ENTITY_SECTIONS 未定義のものが無いこと。
    # .article / .life / .stocks 等エンティティ以外のクラスは対象外（プレフィックスで限定）。
    import re

    html_out = _build_html("朝刊", {"summaries": []}, "2026年6月23日")
    start = html_out.index("<style>")
    end = html_out.index("</style>")
    style_block = html_out[start:end]

    # _ENTITY_SECTIONS が宣言する全 CSS クラス名の集合
    declared = set()
    for section in _ENTITY_SECTIONS:
        for css_key in ("wrapper_css", "item_css", "name_css"):
            declared.add(section[css_key])

    # エンティティ用クラスのプレフィックス（これに合致するものだけ検査対象にする）。
    # _ENTITY_SECTIONS の宣言クラス名から動的に導出し、css 系統追加時の手修正漏れを防ぐ。
    entity_prefixes = tuple(declared)

    # style ブロックからクラストークンを抽出（".foo" / ".foo-bar" 形式）
    found = set(re.findall(r"\.([A-Za-z][\w-]*)", style_block))
    entity_classes = {
        cls
        for cls in found
        if any(cls == p or cls.startswith(p) for p in entity_prefixes)
    }

    undeclared = entity_classes - declared
    assert not undeclared, (
        f"<style> にあるが _ENTITY_SECTIONS 未定義のエンティティ用クラス: {undeclared}"
    )
