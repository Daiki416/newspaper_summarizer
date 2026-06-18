# newspaper — ニュース自動要約・メール配信 Bot

## 概要

RSSフィードからニュースを取得し、Claude AI で要約して Gmail でメール配信する Python CLI ボット。
GitHub Actions で朝刊（7:00 JST）・夕刊（19:00 JST）の2回、自動配信する。

## アーキテクチャ

```
src/
  main.py       エントリーポイント。引数解析 → RSS取得 → AI要約 → メール送信の制御
  fetcher.py    RSSフィードから記事を取得・フィルタリング
  summarizer.py Claude API (Tool Use) でカテゴリ別ニュースを要約
  mailer.py     テキスト＋HTML のMIMEメール組み立て・Gmail SMTP送信
config/
  sources.yaml  カテゴリ別のRSSフィードURL一覧
.cache/
  last_result.json  直前の要約結果キャッシュ（--use-cache で再利用）
.github/workflows/
  newspaper.yml  GitHub Actions スケジュール配信
```

## 依存関係

- **Python 3.13**
- `anthropic` — Claude API クライアント
- `feedparser` — RSS/Atom フィード解析
- `json-repair` — APIレスポンスの壊れたJSONを修復
- `python-dotenv` — .env ファイルの読み込み
- `PyYAML` — sources.yaml の読み込み

インストール:
```bash
pip install -r requirements.txt
```

## 環境変数（.env）

```
ANTHROPIC_API_KEY=   # Anthropic Console で取得
GMAIL_ADDRESS=       # 送信元 Gmail アドレス
GMAIL_APP_PASSWORD=  # Google アカウントのアプリパスワード（16桁）
NOTIFY_EMAIL=        # 送信先（カンマ区切りで複数可）
```

## ローカル実行

```bash
# 通常実行（現在時刻で朝刊/夕刊を自動判定）
python src/main.py

# 朝刊固定
python src/main.py --time morning

# メール送信なしで内容確認
python src/main.py --dry-run

# 過去24時間の記事を対象
python src/main.py --hours 24

# 前回のキャッシュを使用（API呼び出しなし）
python src/main.py --use-cache
```

## 主要な設計上の決定

- **Claude Tool Use**: `output_news_summary` ツールを `tool_choice: required` で強制し、構造化JSONを確実に取得する
- **システムプロンプトキャッシュ**: `cache_control: ephemeral` でAPI費用を節約
- **RSSフィルタリング**: 1フィード最大2件、1カテゴリ最大6件に制限してAPIの入力を抑える
- **キャッシュ機能**: `.cache/last_result.json` に保存し、`--use-cache` で再利用できる
- **朝刊/夕刊判定**: 5〜10時→朝刊、16〜22時→夕刊、それ以外は朝刊をデフォルトとする
- **GitHub Actions concurrency**: `cancel-in-progress: false` で二重送信を防ぐ
- **複数送信先**: `NOTIFY_EMAIL` をカンマ区切りで複数指定可能

## ニュースカテゴリ

| カテゴリ | ソース |
|---|---|
| 国内政治・経済 | NHK 政治、日経 経済 |
| 国内ビジネス | NHK ビジネス、日経 ビジネス、東洋経済オンライン |
| 国内投資・マーケット | 日経 マーケット |
| 国内テクノロジー・科学 | 日経 テクノロジー、ITmedia、日経XTECH、Publickey |
| 国際 | NHK 国際 |

## AI出力スキーマ

```python
{
  "summaries": [{"category", "title", "summary", "url", "source"}],
  "terms": [{"word", "reading", "explanation"}],      # 専門用語 3〜5件
  "stock_picks": [{"ticker", "name", "direction", "reason", "source_headline"}],  # 注目銘柄
  "life_impact": str   # 生活への影響（2〜3文）
}
```

## テスト

現状テストフレームワーク未導入。動作確認は `--dry-run` フラグで行う。
純粋関数（`detect_edition`, `_parse_published`, `_fetch_category` 等）は pytest で単体テスト追加が可能。

```bash
# インストール
pip install pytest

# 実行
python -m pytest
```
