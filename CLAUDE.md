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
  jquants.py    J-Quants 銘柄マスタで「社名→証券コード(Yahooシンボル)」を権威解決
  quotes.py     Yahoo Finance で注目銘柄の現在値・前日比を取得しマージ（コードは jquants 由来）
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
JQUANTS_API_KEY=     # J-Quants の恒久 API キー（社名→証券コードの権威解決に使う・未設定なら注目銘柄は非表示）
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
- **RSSフィルタリング**: 1フィード最大2件、1カテゴリ最大3件に制限してAPIの入力を抑える（記事ごとに4ブロック化したため読みやすさ優先で絞った）
- **対象期間**: 朝1本配信のため、デフォルトで直近24時間の記事を対象にする（main.py `--hours` / Lambda の hours デフォルトとも 24）
- **キャッシュ機能**: `.cache/last_result.json` に保存し、`--use-cache` で再利用できる
- **朝刊/夕刊判定**: 5〜10時→朝刊、16〜22時→夕刊、それ以外は朝刊をデフォルトとする
- **GitHub Actions concurrency**: `cancel-in-progress: false` で二重送信を防ぐ
- **複数送信先**: `NOTIFY_EMAIL` をカンマ区切りで複数指定可能
- **生活への影響は全体で1個**: 記事ごとではなく、今日のニュース全体を踏まえた `life_impact` をトップレベルに1個だけ生成する
- **keywords / companies / people は任意（品質ゲート）**: 該当する場合のみ生成し、無ければ空配列。keywords は 0〜3個に絞る
- **注目銘柄の証券コードは J-Quants で権威解決**: Claude(LLM) は証券コードを記憶から想起し誤コード（実在しないコード→Yahoo 404→価格欠落）を出すため、コード暗記に頼らない。`jquants.py` が J-Quants 銘柄マスタ（`/v2/equities/master`、`x-api-key` ヘッダー認証）から「社名→コード」を引き、価格は引き続き Yahoo Finance で取得する。社名照合は NFKC 正規化＋接尾辞除去した**完全一致のみ**（部分一致・あいまい一致は不採用）。証券コードは5桁・先頭4桁が全数字のときだけ `9418.T` 形式に採用（英数字新形式は安全側で除外）。銘柄マスタはプロセス内キャッシュする。
- **解決不可・キー未設定/障害時は注目銘柄を非表示**: 社名を解決できなかった pick は配信から除外する。`JQUANTS_API_KEY` 未設定や J-Quants 取得失敗時は、誤コード混入を防ぐため注目銘柄を全件除外する（配信自体は止めない）。`stock_picks` スキーマの `ticker` は required から外し、mailer の表示からも削除した（社名＋方向のみ）。

## ニュースカテゴリ

| カテゴリ | ソース |
|---|---|
| 国内政治・経済 | NHK 政治、日経 経済 |
| 国内ビジネス | NHK ビジネス、日経 ビジネス |
| 国内投資・マーケット | 日経 マーケット |
| 国内テクノロジー・科学 | 日経 テクノロジー、ITmedia、日経XTECH、Publickey |
| 国際 | NHK 国際 |

## AI出力スキーマ

```python
{
  "summaries": [{
    "category", "title", "summary",
    "background",                              # なぜ起きたか／前提となる文脈（1〜2文）
    "companies": [{"name", "description"}],    # 企業紹介（任意・該当時のみ、無ければ空配列）
    "people":    [{"name", "description"}],    # 人物紹介（任意・該当時のみ、無ければ空配列）
    "keywords":  [{"word", "note"}],           # キーワード 0〜3件（任意・無ければ空配列）
    "url", "source"
  }],
  "life_impact": str,                          # 全体の生活への影響（全体で1個・2〜3文）
  "stock_picks": [{"name", "direction", "reason", "source_headline"}]  # 注目銘柄（ticker は出さなくてよい＝J-Quants で解決）
}
# required: トップレベルは summaries / life_impact / stock_picks
#           summaries item は category / title / summary / url / source / background
#           （companies / people / keywords は任意＝空配列可、記事ごとの life_impact は廃止）
#           stock_picks item は name / direction / reason / source_headline
#           （ticker は required から外した。プロパティは残るが無視され、証券コードは J-Quants で社名から解決する）
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
