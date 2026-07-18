import os
import sys
import json
import copy

CANDIDATE_FACTOR = 2
_GEMINI_MODEL = "gemini-3.5-flash"

_TOOL = {
    "name": "select_articles",
    "description": "各カテゴリから重要な記事のインデックスを選定して返す",
    "input_schema": {
        "type": "object",
        "properties": {
            "selections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "indices": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                    },
                    "required": ["category", "indices"],
                },
            }
        },
        "required": ["selections"],
    },
}

_SYSTEM_PROMPT = """あなたは投資家・ビジネスパーソン向けニュース選定アシスタントだ。
各カテゴリの候補記事から、投資・ビジネス・政策上の重要度が高い記事を指定件数だけ選ぶ。
選定基準: 市場・企業・政策への影響が大きいもの優先。速報性・独自性も考慮する。"""


def _build_prompt(articles_by_category: dict, limits: dict) -> str:
    lines = ["以下の候補記事から、カテゴリごとに重要な記事を選んでください。\n"]
    for category, articles in articles_by_category.items():
        limit = limits.get(category, 2)
        lines.append(f"## {category}（{limit}件選ぶ）")
        for i, a in enumerate(articles):
            lines.append(f"[{i}] {a['title']} （{a.get('source', '')}）")
        lines.append("")
    return "\n".join(lines)


def _call_gemini_selector(prompt: str) -> dict:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が設定されていません")

    schema = copy.deepcopy(_TOOL["input_schema"])
    tool = types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=_TOOL["name"],
                description=_TOOL["description"],
                parameters=schema,
            )
        ]
    )
    config = types.GenerateContentConfig(
        system_instruction=_SYSTEM_PROMPT,
        tools=[tool],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY",
                allowed_function_names=[_TOOL["name"]],
            )
        ),
        max_output_tokens=2048,
    )

    client = genai.Client(api_key=api_key)
    # MALFORMED_FUNCTION_CALL は複雑なプロンプトで稀に発生するため1回リトライする
    last_err: Exception = ValueError("Gemini 選定 API 呼び出しに失敗しました")
    for _ in range(2):
        response = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=prompt,
            config=config,
        )
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None:
            last_err = ValueError("Gemini 選定 API レスポンスに candidate がありません")
            continue
        if str(candidate.finish_reason) in ("MAX_TOKENS", "FinishReason.MAX_TOKENS", "2"):
            raise ValueError("Gemini 選定 API レスポンスが max_tokens で途中切れしました")
        if candidate.content is None:
            last_err = ValueError(f"Gemini 選定 API の content がありません (finish_reason: {candidate.finish_reason})")
            continue
        for part in candidate.content.parts:
            if part.function_call and part.function_call.name == _TOOL["name"]:
                return json.loads(json.dumps(dict(part.function_call.args)))
        last_err = ValueError("select_articles の function_call が見つかりませんでした")
    raise last_err


def select(articles_by_category: dict, limits: dict) -> dict:
    """Gemini で重要記事を選定して返す。失敗時は候補をそのまま返す。"""
    if not articles_by_category:
        return articles_by_category
    try:
        prompt = _build_prompt(articles_by_category, limits)
        raw = _call_gemini_selector(prompt)
        result = {}
        for sel in raw.get("selections", []):
            category = sel.get("category")
            indices = sel.get("indices", [])
            if category not in articles_by_category:
                continue
            articles = articles_by_category[category]
            picked = [articles[i] for i in indices if 0 <= i < len(articles)]
            if picked:
                result[category] = picked
        # 選定に漏れたカテゴリは上限に切り詰めて残す
        for category, articles in articles_by_category.items():
            if category not in result:
                limit = limits.get(category, 2)
                result[category] = articles[:limit]
        return result
    except Exception as e:
        print(f"記事選定スキップ ({type(e).__name__}): フォールバックで候補をそのまま使用", file=sys.stderr)
        # 候補拡張分を上限に戻してから返す（Claude 切替時のコスト増を防ぐ）
        return {cat: arts[:limits.get(cat, 2)] for cat, arts in articles_by_category.items()}
