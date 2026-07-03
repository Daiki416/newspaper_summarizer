# このファイルは AWS Lambda（コンテナイメージ）で動かすためのエントリーポイントです。
# 既存の CLI ロジック（fetcher / summarizer / mailer）をそのまま再利用しつつ、
# 秘密情報は .env ではなく AWS SSM パラメータストアから取得して環境変数にセットします。

import os
import boto3
from datetime import datetime, timezone, timedelta

# JST = 日本標準時（UTC+9）。朝刊/夕刊の自動判定に使う。
JST = timezone(timedelta(hours=9))

# SSM から環境変数へロードする必須キー（無いと送信不可なので、未登録は致命的エラー）
_REQUIRED_SECRET_KEYS = [
    "ANTHROPIC_API_KEY",
    "GMAIL_ADDRESS",
    "GMAIL_APP_PASSWORD",
    "NOTIFY_EMAIL",
]

# 任意キー（無くても配信は継続する＝ベストエフォート）。未登録でも落とさない。
# J-Quants 銘柄マスタ用の恒久 API キー（社名→証券コードの権威解決に使う）。
# 未登録なら get_name_index() が None を返し、注目銘柄は全件除外して配信を続ける。
# GEMINI_API_KEY は LLM_PROVIDER=gemini 時のみ使用。claude 運用中は未登録でも可。
_OPTIONAL_SECRET_KEYS = [
    "JQUANTS_API_KEY",
    "GEMINI_API_KEY",
]

# SSM から環境変数へロードする対象キー（= そのまま os.environ のキー名になる）
_SECRET_KEYS = _REQUIRED_SECRET_KEYS + _OPTIONAL_SECRET_KEYS


def _load_secrets_from_ssm() -> None:
    """AWS SSM パラメータストアから秘密情報を取得し os.environ にセットする。

    パラメータ名は PARAM_PREFIX + キー名（例: /newspaper/ANTHROPIC_API_KEY）。
    値（秘密情報）は print / log / 例外メッセージに一切含めない。
    必須キー（_REQUIRED_SECRET_KEYS）が未登録の場合のみ、パラメータ名だけを含む
    エラーを送出する。任意キー（_OPTIONAL_SECRET_KEYS）の未登録は許容し配信を止めない。
    """
    prefix = os.environ.get("PARAM_PREFIX", "/newspaper/")
    # パラメータ名 → 環境変数名 の対応表を作る
    name_to_env = {prefix + key: key for key in _SECRET_KEYS}

    ssm = boto3.client("ssm")
    response = ssm.get_parameters(
        Names=list(name_to_env.keys()),
        WithDecryption=True,
    )

    # 取得できたパラメータを対応する環境変数名でセットする
    for param in response["Parameters"]:
        env_name = name_to_env[param["Name"]]
        os.environ[env_name] = param["Value"]

    # 未登録（無効）パラメータのうち「必須キー」が欠けている場合のみ致命的にする。
    # 任意キー（JQUANTS_API_KEY 等）の未登録は無視して配信を続ける（値は出さない）。
    required_names = {prefix + key for key in _REQUIRED_SECRET_KEYS}
    missing_required = [name for name in response["InvalidParameters"] if name in required_names]
    if missing_required:
        raise RuntimeError(f"SSM パラメータが見つかりません: {missing_required}")


# モジュールロード時に SSM から秘密情報をロードする。
# main の import では load_dotenv が走るが override=False なので os.environ は上書きされない。
# 順序を保証するため SSM セットを main 等の import より前に実行する。
_load_secrets_from_ssm()

# SSM セット後に各モジュールを import する（detect_edition は main から再利用する）
from main import detect_edition
from fetcher import fetch_all, load_category_limits
from summarizer import summarize
from selector import select, CANDIDATE_FACTOR
from mailer import send
from storage import save_delivery
from quotes import enrich_stock_prices


def _resolve_edition(event: dict, now: datetime) -> str:
    """event の指定または現在時刻（JST）から朝刊/夕刊を決定する。

    event["edition"] が "morning"→朝刊 / "evening"→夕刊。
    未指定なら渡された now（JST）から detect_edition で自動判定する。
    now は handler で一度だけ取得した値を受け取る（save_delivery と同一時刻を共有）。
    """
    edition_arg = event.get("edition")
    if edition_arg == "morning":
        return "朝刊"
    if edition_arg == "evening":
        return "夕刊"
    return detect_edition(now.hour)


def handler(event, context):
    """Lambda ハンドラ。RSS取得 → AI要約 → メール送信を実行する。

    event:
        hours: 何時間前以降の記事を対象にするか（デフォルト 24）
        edition: "morning" / "evening"（省略時は現在時刻で自動判定）
    """
    # EventBridge から呼ばれた際に event が None になるケースに備える
    event = event or {}

    # EventBridge の input で "24"（文字列）が渡ることがあるため int に正規化する
    # 朝1本配信のため、未指定時は直近24時間を対象にする
    hours = int(event.get("hours", 24))
    # 現在時刻（JST）は一度だけ取得し、edition 判定と S3 保存キーで共有する
    now = datetime.now(JST)
    edition = _resolve_edition(event, now)

    print(f"[{edition}] ニュース取得中... (hours={hours})")
    articles = fetch_all(hours=hours, candidate_factor=CANDIDATE_FACTOR)

    if not articles:
        # 対象記事がなければ要約・送信をスキップする（件数のみログ）
        print("対象記事が見つかりませんでした。要約・送信をスキップします。")
        return {"edition": edition, "hours": hours, "article_count": 0, "sent": False}

    total = sum(len(v) for v in articles.values())
    print(f"  取得: {total}件（{len(articles)}カテゴリ）")
    articles = select(articles, load_category_limits())

    from summarizer import LLM_PROVIDER
    print(f"{LLM_PROVIDER.capitalize()} APIで要約中...")
    result = summarize(articles)

    # 注目銘柄に Yahoo の現在値・前日比をベストエフォートでマージする（send の前）。
    # S3 保存は send の後なので、S3 には価格込みで保存される（許容）。
    result["stock_picks"] = enrich_stock_prices(result.get("stock_picks", []))

    print("メール送信中...")
    send(edition, result, dry_run=False)

    # ベストエフォートでS3へ蓄積保存（失敗しても配信成功は壊さない）
    try:
        key = save_delivery(result, edition, now)
        if key:
            print(f"S3保存: bucket={os.environ.get('CACHE_BUCKET')} key={key}")
    except Exception as error:
        # 秘密情報を出さない。例外型名のみ（バケット名は出してよいが API キー等は厳禁）
        print(f"S3保存に失敗（配信は成功）: {type(error).__name__}")

    # 戻り値には秘密情報を含めない（最小限の実行結果のみ）
    return {
        "edition": edition,
        "hours": hours,
        "article_count": total,
        "category_count": len(articles),
        "sent": True,
    }
