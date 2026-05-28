# このファイルはClaude AI APIを呼び出してニュースを要約する処理を担当します。
# 記事テキストをAIに送り、要約・用語解説・注目銘柄・生活への影響を
# 決まった形式（構造化データ）で返してもらいます。

import json

import anthropic
from json_repair import repair_json

# 使用するClaudeモデルの名前
MODEL = "claude-sonnet-4-6"

# AIへの指示文（システムプロンプト）。AIの役割や出力ルールをここで定義する
SYSTEM_PROMPT = """あなたは投資家・ビジネスパーソン向けの日本語ニュース要約・解説アシスタントです。
与えられたニュース記事を要約し、市場・ビジネス・政策上の含意を意識した解説を生成してください。

【要約のルール】
- 各記事を2〜3文で簡潔に要約する
- 投資・ビジネスへの影響・示唆を含める
- 客観的・中立的なトーンを保つ

【用語のルール】
- summaries 全体を通じて重要な専門用語を3〜5件ピックアップする
- 政治・経済・金融・投資・テクノロジーの専門用語を優先する
- 中学生でもわかるような平易な言葉で解説する

【注目銘柄候補のルール】
- 提供ニュースに明確な根拠がある場合のみ国内個別株を1〜3件ピックアップする
- 根拠となるニュースが存在しない場合は空リストにする
- 方向感は「↑上昇期待」「↓下落懸念」「→様子見」のいずれかを使用する
- これは投資助言ではなく情報提供であることを念頭に置く

【生活への影響のルール】
- 今日のニュース全体を踏まえ、読者の日常生活（物価・サービス・雇用・インフラ等）に影響が出そうな内容を2〜3文でまとめる
- Source フィールドに記載された出典名は変更せずそのまま source フィールドに出力すること"""

# Tool Use（ツール使用）の定義。
# AIに「この形式でデータを返してください」と指定するための仕組みで、
# JSON Schema（データ構造の設計図）でフィールド名・型・必須項目を定義する。
# これにより自由形式のテキストではなく、プログラムで扱いやすい構造化データが得られる。
_TOOL = {
    "name": "output_news_summary",
    "description": "ニュース要約と用語解説を構造化データとして出力する",
    "input_schema": {
        "type": "object",
        "properties": {
            # summaries: カテゴリ・タイトル・要約文・URLを含む記事要約のリスト
            "summaries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "url": {"type": "string"},
                        "source": {"type": "string"},
                    },
                    "required": ["category", "title", "summary", "url", "source"],
                },
            },
            # terms: 今日のニュースに登場した専門用語とその解説のリスト
            "terms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "word": {"type": "string"},
                        "reading": {"type": "string"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["word", "reading", "explanation"],
                },
            },
            # stock_picks: ニュースを根拠とした注目銘柄候補のリスト
            "stock_picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ticker": {"type": "string"},
                        "name": {"type": "string"},
                        "direction": {"type": "string", "enum": ["↑上昇期待", "↓下落懸念", "→様子見"]},
                        "reason": {"type": "string"},
                        "source_headline": {"type": "string"},
                    },
                    "required": ["ticker", "name", "direction", "reason", "source_headline"],
                },
            },
            # life_impact: 生活への影響をまとめた文章（1つの文字列）
            "life_impact": {"type": "string"},
        },
        "required": ["summaries", "terms", "stock_picks", "life_impact"],
    },
}


def summarize(articles_by_category: dict[str, list[dict]]) -> dict:
    """記事群をClaude APIで要約し、用語解説も生成する。

    Args:
        articles_by_category: fetch_all() の返り値
    Returns:
        {"summaries": [...], "terms": [...], "stock_picks": [...], "life_impact": "..."}
    """
    # 記事がひとつもない場合は空の結果をそのまま返す
    if not articles_by_category:
        return {"summaries": [], "terms": [], "stock_picks": [], "life_impact": ""}

    def _sanitize(text: str) -> str:
        # AIへ渡すテキストに含まれる「スマートクォート」（""）を
        # 通常のダブルクォート（"）に統一する。
        # スマートクォートはJSONを壊す原因になるため事前に除去しておく。
        return text.replace('"', '"').replace('"', '"')

    # --- AIへ送るプロンプト（入力テキスト）を組み立てる ---
    # Markdown形式（## カテゴリ、### 記事タイトル）で構造化すると
    # AIが内容を理解しやすくなる
    lines = []
    for category, articles in articles_by_category.items():
        lines.append(f"\n## {category}")
        for a in articles:
            lines.append(f"### {_sanitize(a['title'])}")
            lines.append(f"URL: {a['url']}")
            lines.append(f"Source: {a.get('source', '')}")
            if a["summary"]:
                lines.append(_sanitize(a["summary"]))

    user_content = "\n".join(lines)

    # --- Claude API を呼び出して要約を取得する ---
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,  # AIが出力できる最大トークン数（文字数の目安）
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                # cache_control: システムプロンプトをAPIサーバー側でキャッシュし
                # 毎回送信するコストを削減する（Anthropic のプロンプトキャッシュ機能）
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_TOOL],
        # tool_choice: 必ず指定したツールを使って出力させる
        tool_choice={"type": "tool", "name": "output_news_summary"},
        messages=[
            {
                "role": "user",
                "content": f"以下のニュース記事を要約し、今日の用語を抽出してください。\n{user_content}",
            }
        ],
    )

    # --- APIレスポンスの検証 ---
    if not response.content:
        raise ValueError("APIレスポンスのcontentが空です")
    if response.stop_reason == "max_tokens":
        # max_tokens に達すると出力が途中で切れるため、不完全なデータになってしまう
        raise ValueError("APIレスポンスがmax_tokensで途中切れしました")

    # レスポンスの中から tool_use ブロック（ツール呼び出し結果）を探す
    for block in response.content:
        if block.type == "tool_use" and block.name == "output_news_summary":
            result = block.input
            # まれにAIがリストをJSON文字列として返すことがある
            # json_repair はそのような壊れたJSONも修復して解析できるライブラリ
            for key in ("summaries", "terms", "stock_picks"):
                if isinstance(result.get(key), str):
                    result[key] = json.loads(repair_json(result[key]))
            return result

    # ここに到達するのは予期しないレスポンス構造の場合のみ
    raise ValueError("tool_use ブロックが見つかりませんでした")
