# Lambda 本番配信のたびに summarize の result を S3 へ日付つきで蓄積保存するための
# 純粋関数群。CACHE_BUCKET が設定されているときのみ動作し、未設定なら完全 no-op。
# 秘密情報は一切扱わない（保存対象は summarize の result のみ）。

import json
import os
from datetime import datetime

# S3 オブジェクトキーの先頭プレフィックスと拡張子（散在防止のため定数化）
KEY_PREFIX = "deliveries"
KEY_EXT = ".json"

# S3 へ保存する result のトップレベルキーのホワイトリスト。
# 将来 result に想定外のフィールド（デバッグ情報等）が混入しても保存対象を絞る保険。
# stock_picks 要素内の enrich 済みフィールド（price/change_pct/as_of/yahoo_symbol）は
# トップレベルではないためこのフィルタの対象外で、そのまま保持される。
_SAVE_TOP_LEVEL_KEYS = ("summaries", "life_impact", "stock_picks")


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

    契約: now_jst は tz-aware（JST）な datetime を受け取る。naive な datetime
    （tzinfo is None）が渡された場合は ValueError を送出する（暗黙の UTC 解釈で
    日付がずれた S3 キーが生成されるのを防ぐ明示エラー方式）。
    """
    if now_jst.tzinfo is None:
        raise ValueError("build_key には tz-aware な datetime を渡してください（naive 不可）")
    return (
        f"{KEY_PREFIX}/{now_jst:%Y}/{now_jst:%m}/"
        f"{now_jst:%Y-%m-%d}-{edition}{KEY_EXT}"
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
    # トップレベルをホワイトリストに限定して保存する（存在するキーのみ）。
    # 要素内（stock_picks の enrich フィールド等）はフィルタせずそのまま保持する。
    filtered = {k: result[k] for k in _SAVE_TOP_LEVEL_KEYS if k in result}
    body = json.dumps(filtered, ensure_ascii=False).encode("utf-8")

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
