# このファイルはClaude AI APIを呼び出してニュースを要約する処理を担当します。
# 記事テキストをAIに送り、各記事ごとの要約・背景・企業紹介・人物紹介・キーワードと、
# 全体の生活への影響・注目銘柄を決まった形式（構造化データ）で返してもらいます。

import os

import anthropic
from json_repair import repair_json

# 使用するClaudeモデルの名前
MODEL = "claude-sonnet-4-6"
GEMINI_MODEL = "gemini-2.5-flash"

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "claude").lower()

# AIへの指示文（システムプロンプト）。AIの役割や出力ルールをここで定義する
SYSTEM_PROMPT = """あなたは投資家・ビジネスパーソン向けの日本語ニュース要約・解説アシスタントです。
与えられたニュース記事を要約し、市場・ビジネス・政策上の含意を意識した解説を生成してください。

各記事(summaries の各要素)について、必須なのは summary・background のみです。
life_impact（生活への影響）は記事ごとではなく、全体で1個だけトップレベルに生成してください。
companies（企業紹介）・people（人物紹介）・keywords（キーワード）は、該当する場合のみ生成し、
無ければ空配列にしてください。

【文体のルール】
- summary / background / life_impact / companies.description / people.description / keywords.note はすべて「だ・である調」で書く（「〜です」「〜ます」は使わない）

【要約のルール】
- 各記事の summary を2〜3文で簡潔に要約する
- 投資・ビジネスへの影響・示唆を含める
- 客観的・中立的なトーンを保つ

【背景のルール】
- 各記事の background に「なぜ起きたか／前提となる文脈」を1〜2文で書く

【生活への影響のルール（全体）】
- 今日のニュース全体を踏まえ、トップレベルの life_impact に、
  読者の日常（物価・サービス・雇用・インフラ等）への影響を2〜3文で書く
- 記事ごとには生活への影響を書かない（全体で1個だけ）

【キーワードのルール】
- 各記事の keywords は 0〜3個。本当に説明する価値のある用語のみを選ぶ
- 日常語・文脈で自明な語は選ばない
- 「一般読者が知らなそうな」という制約は付けない
- 政治・経済の用語はやや初歩的でも積極採用してよい
- 該当が無ければ空配列にする
- 各要素は word（単語）と note（中学生でもわかる一言解説）を持つ
- reading（読み仮名）は付けない

【企業紹介のルール】
- 記事に登場する主要企業を companies に {name, description} の形で書く
- description は「何をやっている会社か・強み・今どういう状況か」を1〜2文で書く
- 誰もが知る大企業も含めてよい
- 該当が無ければ空配列にする

【人物紹介のルール】
- 記事に登場する重要人物を people に {name, description} の形で書く
- description は「何者か（役職・立場）・なぜこの記事で重要か」を1〜2文で書く
- 該当が無ければ空配列にする

【注目銘柄候補のルール】
- 提供ニュースに明確な根拠がある場合のみ国内個別株を1〜3件ピックアップする
- 根拠となるニュースが存在しない場合は空リストにする
- 方向感は「↑上昇期待」「↓下落懸念」「→様子見」のいずれかを使用する
- name には正確な現在の正式社名を出すこと。証券コードは出さなくてよい（こちらで権威的に解決する）
- これは投資助言ではなく情報提供であることを念頭に置く

- Source フィールドに記載された出典名は変更せずそのまま source フィールドに出力すること

highlights には、今日の summaries の中から最重要ニュース 1〜2 件を選んでください。
- summaries 配列の 0-based index を指定すること
- 生活・物価・雇用・身近なサービスへの影響が大きいものを優先する"""

# Tool Use（ツール使用）の定義。
# AIに「この形式でデータを返してください」と指定するための仕組みで、
# JSON Schema（データ構造の設計図）でフィールド名・型・必須項目を定義する。
# これにより自由形式のテキストではなく、プログラムで扱いやすい構造化データが得られる。
_TOOL = {
    "name": "output_news_summary",
    "description": (
        "各記事の要約・背景・企業紹介・人物紹介・キーワードと、"
        "全体の生活への影響・注目銘柄候補を構造化データとして出力する"
    ),
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
                        "background": {"type": "string"},
                        "companies": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                                "required": ["name", "description"],
                            },
                        },
                        "people": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "description": {"type": "string"},
                                },
                                "required": ["name", "description"],
                            },
                        },
                        "keywords": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "word": {"type": "string"},
                                    "note": {"type": "string"},
                                },
                            },
                        },
                        "url": {"type": "string"},
                        "source": {"type": "string"},
                    },
                    "required": [
                        "category",
                        "title",
                        "summary",
                        "url",
                        "source",
                        "background",
                    ],
                },
            },
            # life_impact: 今日のニュース全体を踏まえた生活への影響（全体で1個）
            "life_impact": {"type": "string"},
            # highlights: 今日の最重要ニュース 1〜2 件（summaries の 0-based index で参照）
            "highlights": {
                "type": "array",
                "description": "今日の最重要ニュース1〜2件。summaries 配列の 0-based index で参照する",
                "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "summaries 配列の 0-based index"
                        }
                    },
                    "required": ["index"]
                }
            },
            # stock_picks: ニュースを根拠とした注目銘柄候補のリスト
            "stock_picks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        # ticker プロパティ自体は残すが required からは外す（無視される）。
                        # 証券コードは J-Quants 銘柄マスタで社名から権威解決する。
                        "ticker": {"type": "string"},
                        "name": {"type": "string"},
                        "direction": {"type": "string", "enum": ["↑上昇期待", "↓下落懸念", "→様子見"]},
                        "reason": {"type": "string"},
                        "source_headline": {"type": "string"},
                    },
                    "required": ["name", "direction", "reason", "source_headline"],
                },
            },
        },
        "required": ["summaries", "life_impact", "stock_picks", "highlights"],
    },
}


# 任意フィールド（無ければ空配列）。正規化ループからのみ参照する。
# 設計経緯（keywords だけ CSS 別系統である理由等）は _normalize_entity_fields の docstring 参照。
_OPTIONAL_LIST_FIELDS = ("keywords", "companies", "people")


def _normalize_entity_fields(summaries: list) -> None:
    """各記事の keywords / companies / people の3フィールドを正規化する（in-place・返り値 None）。

    AIの出力ゆれに対する防御処理:
        - summaries の要素が非dict（str等）の場合はスキップする
        - 各フィールドが欠落していれば空配列にする
        - 各フィールドが文字列の場合は repair_json で解析してリスト化する
        - list でなければ空配列にする
        - 各フィールドの要素が非dict（["インフレ", "金利"] のようなstr）は除去する

    これにより mailer 側の `.get('word')` 等が AttributeError を起こして
    朝刊/夕刊が丸ごと配信失敗するのを防ぐ。

    設計メモ: _TOOL スキーマ上 companies/people は {name,description}、keywords は
    {word,note} と items 形状が異なる。3フィールドは正規化ポリシー（dict のみ残し
    値を str 化）が共通なため本関数で一括処理し、形状差はスキーマ側に閉じている。
    """
    for item in summaries:
        if not isinstance(item, dict):
            continue
        for field in _OPTIONAL_LIST_FIELDS:
            item.setdefault(field, [])
            if isinstance(item[field], str):
                # AIが "該当なし" / "なし" / "" / 空白のみ といった
                # 「JSON配列でない素の文字列」を返すケースに備える。
                # repair_json(..., return_objects=True) は修復後の Python オブジェクト
                # を直接返す（json.loads との二重パース不要）。素の文字列は '' を返し、
                # 直後の list 判定で [] に落ちるため、防御処理自体はクラッシュしない。
                try:
                    item[field] = repair_json(item[field], return_objects=True)
                except (ValueError, TypeError):
                    item[field] = []
            if not isinstance(item[field], list):
                item[field] = []
            # 最終的に dict 要素のみを残し、各値を str 化する。
            # mailer 側の html.escape() は str を前提とするため、
            # 値が int 等でも AttributeError で落ちないよう正規化する。
            item[field] = [
                {k: str(v) for k, v in entity.items()}
                for entity in item[field]
                if isinstance(entity, dict)
            ]


def _sanitize(text: str) -> str:
    """AIへ渡すテキストの「スマートクォート」を通常のダブルクォート（"）に統一する。

    スマートクォートはJSONを壊す原因になるため事前に除去しておく。
    変換対象: U+201C / U+201D → U+0022（"）。
    ※エディタ/linter が全角クォートを ASCII に正規化して no-op 化するのを防ぐため、
      置換対象は \\u エスケープ（ASCII表記）で明示する。
    """
    return text.replace("“", '"').replace("”", '"')


def _build_user_content(articles_by_category: dict) -> str:
    """カテゴリ別記事をAIへ送るMarkdown形式のプロンプト文字列に変換する。"""
    lines = []
    for category, articles in articles_by_category.items():
        lines.append(f"\n## {category}")
        for article in articles:
            lines.append(f"### {_sanitize(article['title'])}")
            lines.append(f"URL: {article['url']}")
            lines.append(f"Source: {article.get('source', '')}")
            if article["summary"]:
                lines.append(_sanitize(article["summary"]))
    return "\n".join(lines)


def _postprocess(result: dict) -> dict:
    """APIレスポンスの生 dict を防御的に正規化して返す。"""
    for key in ("summaries", "stock_picks"):
        result.setdefault(key, [])
        if isinstance(result.get(key), str):
            try:
                result[key] = repair_json(result[key], return_objects=True)
            except (ValueError, TypeError):
                result[key] = []
    _normalize_entity_fields(result["summaries"])
    result.setdefault("life_impact", "")
    result.setdefault("highlights", [])
    if not isinstance(result["highlights"], list):
        result["highlights"] = []
    summaries_len = len(result.get("summaries", []))
    result["highlights"] = [
        h for h in result["highlights"]
        if isinstance(h, dict)
        and isinstance(h.get("index"), int)
        and 0 <= h["index"] < summaries_len
    ]
    return result


def _call_claude(user_content: str) -> dict:
    """Claude API を呼び出し、後処理前の生 result dict を返す。"""
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=MODEL,
        # AIが出力できる最大トークン数（文字数の目安）。
        # 記事ごとに summary+background+companies+people+keywords を出力するため
        # 出力量が増えており、途中切れ（max_tokens）による配信失敗を避けるため引き上げている。
        max_tokens=16384,
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
                "content": (
                    "以下のニュース記事を、各記事ごとに要約・背景を付け、"
                    "該当する場合は企業紹介・人物紹介・キーワードを添えて出力してください。"
                    "生活への影響は記事ごとではなく、全体で1個だけ life_impact に書いてください。\n"
                    f"{user_content}"
                ),
            }
        ],
    )

    if not response.content:
        raise ValueError("APIレスポンスのcontentが空です")
    if response.stop_reason == "max_tokens":
        raise ValueError("APIレスポンスがmax_tokensで途中切れしました")

    for block in response.content:
        if block.type == "tool_use" and block.name == "output_news_summary":
            return block.input

    raise ValueError("tool_use ブロックが見つかりませんでした")


def _call_gemini(user_content: str) -> dict:
    """Gemini API を呼び出し、後処理前の生 result dict を返す。"""
    import copy
    import json

    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY が設定されていません")

    # Claude の _TOOL スキーマを流用。Gemini 非対応の maxItems のみ除去
    schema = copy.deepcopy(_TOOL["input_schema"])
    schema["properties"]["highlights"].pop("maxItems", None)

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
        system_instruction=SYSTEM_PROMPT,
        tools=[tool],
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(
                mode="ANY",
                allowed_function_names=[_TOOL["name"]],
            )
        ),
        max_output_tokens=16384,
    )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_content,
        config=config,
    )

    candidate = response.candidates[0] if response.candidates else None
    if candidate is None:
        raise ValueError("Gemini APIレスポンスにcandidateがありません")
    # finish_reason が MAX_TOKENS の場合は途中切れ
    if str(candidate.finish_reason) in ("MAX_TOKENS", "FinishReason.MAX_TOKENS", "2"):
        raise ValueError("Gemini APIレスポンスがmax_tokensで途中切れしました")
    # safety block 等で content が返らないケースを明示的に検査する
    if candidate.content is None:
        raise ValueError(f"Gemini APIレスポンスのcontentがありません (finish_reason: {candidate.finish_reason})")

    for part in candidate.content.parts:
        if part.function_call and part.function_call.name == _TOOL["name"]:
            args = part.function_call.args
            # proto の MapComposite を Python ネイティブ dict に変換
            result = json.loads(json.dumps(dict(args)))
            return result

    raise ValueError("Gemini レスポンスに function_call ブロックが見つかりませんでした")


def summarize(articles_by_category: dict[str, list[dict]]) -> dict:
    """記事群をAI APIで要約し、各記事の背景・企業/人物/キーワードと全体の生活影響も生成する。

    Args:
        articles_by_category: fetch_all() の返り値
    Returns:
        {"summaries": [...], "life_impact": "...", "stock_picks": [...], "highlights": [...]}
    """
    if not articles_by_category:
        return {"summaries": [], "life_impact": "", "stock_picks": [], "highlights": []}

    user_content = _build_user_content(articles_by_category)

    if LLM_PROVIDER == "gemini":
        try:
            result = _call_gemini(user_content)
        except Exception as e:
            if type(e).__name__ == "ServerError":
                print(f"Gemini API 一時障害 ({type(e).__name__})、Claudeにフォールバックします")
                result = _call_claude(user_content)
            else:
                raise
    elif LLM_PROVIDER == "claude":
        try:
            result = _call_claude(user_content)
        except anthropic.InternalServerError as e:
            if not os.environ.get("GEMINI_API_KEY"):
                raise
            print(f"Claude API 一時障害 ({type(e).__name__})、Geminiにフォールバックします")
            result = _call_gemini(user_content)
    else:
        raise ValueError(
            f"未対応のLLM_PROVIDER: {LLM_PROVIDER!r} (claude または gemini を指定してください)"
        )

    return _postprocess(result)
