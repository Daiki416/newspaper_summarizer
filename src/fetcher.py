# このファイルはRSSフィードからニュース記事を取得する処理を担当します。
# RSS（Really Simple Syndication）とは、ニュースサイトが記事の更新情報を
# 配信するための仕組みです。feedparserというライブラリでRSSを読み込んでいます。

import re
import feedparser
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ニュースソース（取得先URL）の設定ファイルのパス
CONFIG_PATH = Path(__file__).parent.parent / "config" / "sources.yaml"
# 日本標準時（UTC+9）の定義
JST = timezone(timedelta(hours=9))
# 1フィードあたりの最大記事数（1ソースが枠を独占しないようにする）
MAX_ARTICLES_PER_FEED = 2
# 1カテゴリあたりの最大取得記事数（多すぎるとAIへの入力が長くなるため制限する）
MAX_ARTICLES_PER_CATEGORY = 6


def _load_sources() -> dict:
    """sources.yamlを読み込んでカテゴリ別フィードURLの辞書を返す。

    YAML（ヤムル）とは設定ファイルによく使われるテキスト形式です。
    """
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise SystemExit(f"設定ファイルが見つかりません: {CONFIG_PATH}")
    except yaml.YAMLError as e:
        raise SystemExit(f"設定ファイルの形式が不正です: {e}")


def _parse_published(entry) -> datetime | None:
    """RSSエントリから公開日時を取得してdatetimeオブジェクトに変換する。

    RSSの日時フィールドは配信元によって名前が異なる（published / updated）ため、
    どちらも試みるようにしている。
    """
    # published_parsed が存在する場合はそれを使う（最も一般的なフィールド名）
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    # published がない場合は updated で代用する
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
    # 日時情報が全く取れない場合は None を返す
    return None


def _fetch_category(feeds: list[dict], cutoff: datetime) -> list[dict]:
    """1カテゴリ分のフィードをすべて取得し、新しい記事だけを返す。

    Args:
        feeds: sources.yamlから読み込んだ {url, name} のリスト
        cutoff: これより古い記事は除外する基準日時
    Returns:
        記事の辞書のリスト（新しい順・最大 MAX_ARTICLES_PER_CATEGORY 件）
    """
    articles = []
    for feed in feeds:
        # feedparserがRSSのURLを読み込んで解析する
        parsed = feedparser.parse(feed["url"])
        feed_count = 0  # このフィードから取得した記事数
        for entry in parsed.entries:
            # 1フィードから取りすぎないよう上限を設ける
            if feed_count >= MAX_ARTICLES_PER_FEED:
                break
            pub = _parse_published(entry)
            # カットオフより古い記事はスキップ（continue で次のループへ）
            if pub and pub < cutoff:
                continue
            summary = getattr(entry, "summary", "") or ""
            # feedparser wraps HTML — strip tags simply
            # RSSの概要欄にはHTMLタグ（<br>や<p>など）が混入することがある
            # 正規表現で <タグ> の形をすべて削除してプレーンテキストに変換する
            summary = re.sub(r'<[^>]+>', '', summary).strip()
            articles.append({
                "title": entry.get("title", ""),
                "url": entry.get("link", ""),
                # 日時を「HH:MM」形式の文字列に変換（メール表示用）
                "published": pub.astimezone(JST).strftime("%H:%M") if pub else "",
                # ソート用に日時オブジェクトを一時的に保持する（後で削除）
                "_pub_dt": pub,
                # 概要は長すぎてもAIに渡しにくいので400文字で切り捨てる
                "summary": summary[:400],
                "source": feed["name"],
            })
            feed_count += 1
    # newest first, then cap
    # 新しい記事が先頭に来るよう降順ソートする
    articles.sort(key=lambda a: a["_pub_dt"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    # ソート用の一時フィールドは不要なので削除する
    for a in articles:
        del a["_pub_dt"]
    # 上位 MAX_ARTICLES_PER_CATEGORY 件だけ返す
    return articles[:MAX_ARTICLES_PER_CATEGORY]


def fetch_all(hours: int = 12) -> dict[str, list[dict]]:
    """RSSフィードから全カテゴリの記事を取得する。

    Args:
        hours: 何時間前以降の記事を対象にするか
    Returns:
        {カテゴリ名: [記事dict, ...]} の辞書
    """
    # 現在時刻から hours 時間前を「カットオフ（取得の締め切り時刻）」とする
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    sources = _load_sources()
    result = {}
    for category, feeds in sources.items():
        articles = _fetch_category(feeds, cutoff)
        # 記事が1件もなかったカテゴリは結果に含めない
        if articles:
            result[category] = articles
    return result
