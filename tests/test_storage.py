import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest  # noqa: E402

from storage import normalize_edition, build_key, save_delivery  # noqa: E402

JST = timezone(timedelta(hours=9))


class DummyS3Client:
    """put_object の呼び出し引数を記録するスタブ。"""

    def __init__(self):
        self.calls = []

    def put_object(self, **kwargs):
        self.calls.append(kwargs)


class RaisingS3Client:
    """put_object が必ず例外を投げるスタブ。"""

    def put_object(self, **kwargs):
        raise RuntimeError("S3 put failed")


# --- normalize_edition ---


def test_normalize_edition_japanese_morning():
    assert normalize_edition("朝刊") == "morning"


def test_normalize_edition_japanese_evening():
    assert normalize_edition("夕刊") == "evening"


def test_normalize_edition_idempotent_morning():
    assert normalize_edition("morning") == "morning"


def test_normalize_edition_idempotent_evening():
    assert normalize_edition("evening") == "evening"


def test_normalize_edition_unknown():
    assert normalize_edition("号外") == "unknown"


# --- build_key ---


def test_build_key_basic():
    now = datetime(2026, 6, 19, 7, 0, 0, tzinfo=JST)
    assert build_key(now, "morning") == "deliveries/2026/06/2026-06-19-morning.json"


def test_build_key_zero_padded_month():
    now = datetime(2026, 1, 5, 19, 0, 0, tzinfo=JST)
    assert build_key(now, "evening") == "deliveries/2026/01/2026-01-05-evening.json"


# --- save_delivery ---


def test_save_delivery_no_bucket_is_noop(monkeypatch):
    monkeypatch.delenv("CACHE_BUCKET", raising=False)
    client = DummyS3Client()
    now = datetime(2026, 6, 19, 7, 0, 0, tzinfo=JST)
    result = save_delivery({"a": 1}, "朝刊", now, bucket=None, s3_client=client)
    assert result is None
    assert client.calls == []


def test_save_delivery_with_bucket_arg():
    client = DummyS3Client()
    now = datetime(2026, 6, 19, 7, 0, 0, tzinfo=JST)
    result = {"summaries": [{"title": "日本語タイトル"}]}
    key = save_delivery(result, "朝刊", now, bucket="my-bucket", s3_client=client)

    assert key == "deliveries/2026/06/2026-06-19-morning.json"
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Bucket"] == "my-bucket"
    assert call["Key"] == "deliveries/2026/06/2026-06-19-morning.json"
    assert call["ContentType"] == "application/json"

    body = call["Body"]
    assert isinstance(body, bytes)
    decoded = body.decode("utf-8")
    # ensure_ascii=False なので日本語が \uXXXX エスケープされていない
    assert "日本語タイトル" in decoded
    assert "\\u" not in decoded


def test_save_delivery_bucket_from_env(monkeypatch):
    monkeypatch.setenv("CACHE_BUCKET", "env-bucket")
    client = DummyS3Client()
    now = datetime(2026, 6, 19, 19, 0, 0, tzinfo=JST)
    key = save_delivery({"x": 1}, "夕刊", now, s3_client=client)

    assert key == "deliveries/2026/06/2026-06-19-evening.json"
    assert len(client.calls) == 1
    assert client.calls[0]["Bucket"] == "env-bucket"


def test_save_delivery_empty_result():
    client = DummyS3Client()
    now = datetime(2026, 6, 19, 7, 0, 0, tzinfo=JST)
    save_delivery({}, "morning", now, bucket="my-bucket", s3_client=client)
    assert client.calls[0]["Body"] == b"{}"


def test_save_delivery_propagates_s3_error():
    client = RaisingS3Client()
    now = datetime(2026, 6, 19, 7, 0, 0, tzinfo=JST)
    with pytest.raises(RuntimeError):
        save_delivery({"a": 1}, "morning", now, bucket="my-bucket", s3_client=client)
