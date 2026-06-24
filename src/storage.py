# Lambda 本番配信のたびに summarize の result を S3 へ日付つきで蓄積保存するための
# 純粋関数群。CACHE_BUCKET が設定されているときのみ動作し、未設定なら完全 no-op。
# 秘密情報は一切扱わない（保存対象は summarize の result のみ）。

import os
import json
from datetime import datetime


def normalize_edition(edition: str) -> str:
    """朝刊→'morning' / 夕刊→'evening'。

    'morning' / 'evening' はそのまま通す（冪等）。それ以外は 'unknown'。
    """
    mapping = {
        "朝刊": "morning",
        "夕刊": "evening",
        "morning": "morning",
        "evening": "evening",
    }
    return mapping.get(edition, "unknown")


def build_key(now_jst: datetime, edition: str) -> str:
    """S3 オブジェクトキーを生成する。

    'deliveries/YYYY/MM/YYYY-MM-DD-{edition}.json' を返す。
    edition は normalize 済みを受け取る前提。月はゼロ埋めされる。
    """
    return (
        f"deliveries/{now_jst:%Y}/{now_jst:%m}/"
        f"{now_jst:%Y-%m-%d}-{edition}.json"
    )


def save_delivery(
    result: dict,
    edition: str,
    now_jst: datetime,
    *,
    bucket: str | None = None,
    s3_client=None,
) -> str | None:
    """result を S3 に保存し、保存したキーを返す。no-op 時は None。

    bucket は引数優先、None なら環境変数 CACHE_BUCKET を参照する。
    bucket が falsy なら完全 no-op（put_object も boto3.client も呼ばない）。
    例外は握りつぶさず呼び出し側に伝播させる。
    """
    if bucket is None:
        bucket = os.environ.get("CACHE_BUCKET")
    if not bucket:
        return None

    key = build_key(now_jst, normalize_edition(edition))
    body = json.dumps(result, ensure_ascii=False).encode("utf-8")

    if s3_client is None:
        import boto3

        s3_client = boto3.client("s3")

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
    )
    return key
