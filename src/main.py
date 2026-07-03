#!/usr/bin/env python3
# このファイルはアプリ全体の入り口（エントリーポイント）です。
# ニュース取得 → AI要約 → メール送信の一連の流れをここで制御します。

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

# .envファイルから環境変数（APIキーやメールアドレスなど秘密情報）を読み込む
# .envファイルはプロジェクトルートに置かれ、Gitには含めないことで情報漏洩を防ぐ
load_dotenv(Path(__file__).parent.parent / ".env")

# 同じプロジェクト内の他モジュールを読み込む
from fetcher import fetch_all, load_category_limits
from summarizer import summarize
from selector import select, CANDIDATE_FACTOR
from mailer import send
from quotes import enrich_stock_prices

# JST = 日本標準時（UTC+9）。Pythonの日時処理はデフォルトでUTCを使うため明示的に定義する
JST = timezone(timedelta(hours=9))
# キャッシュファイルのパス。前回の要約結果を保存し、再利用できるようにする
CACHE_PATH = Path(__file__).parent.parent / ".cache" / "last_result.json"


def detect_edition(hour: int) -> str:
    """現在時刻から朝刊/夕刊を判定する。

    Args:
        hour: 現在の時刻（0〜23の整数）
    Returns:
        "朝刊" または "夕刊" の文字列
    """
    # 5〜10時は朝刊の配信時間帯
    if 5 <= hour < 11:
        return "朝刊"
    # 16〜22時は夕刊の配信時間帯
    if 16 <= hour < 23:
        return "夕刊"
    return "朝刊"  # スケジュール外で手動実行された場合のデフォルト


def main() -> None:
    """アプリケーション全体の処理を順番に実行するメイン関数。"""

    # argparse はコマンドラインから引数（オプション）を受け取るための標準ライブラリ
    # 例: python main.py --dry-run --hours 6
    parser = argparse.ArgumentParser(description="ニュース自動要約・メール通知")
    parser.add_argument(
        "--time",
        choices=["morning", "evening"],
        help="配信タイミングを強制指定（省略時は現在時刻から自動判定）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",  # 指定されると True になるフラグ（値は不要）
        help="メールを送信せず標準出力に表示する",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="何時間前以降の記事を対象にするか（デフォルト: 24）",
    )
    parser.add_argument(
        "--use-cache",
        action="store_true",
        help="直前の要約結果キャッシュを使用し、RSS取得とClaude API呼び出しをスキップする",
    )
    args = parser.parse_args()

    # --- 朝刊/夕刊の判定 ---
    if args.time == "morning":
        edition = "朝刊"
    elif args.time == "evening":
        edition = "夕刊"
    else:
        # --time が省略された場合は現在時刻で自動判定
        hour = datetime.now(JST).hour
        edition = detect_edition(hour)

    try:
        if args.use_cache:
            # キャッシュモード: 前回保存した要約結果をそのまま使う
            # API呼び出しを節約したいときや、動作確認時に便利
            if not CACHE_PATH.exists():
                print("キャッシュファイルが見つかりません。先に通常実行してください。", file=sys.stderr)
                sys.exit(1)
            print("（キャッシュ使用）Claude APIおよびRSSフェッチをスキップします")
            # JSON形式で保存されたキャッシュファイルを読み込んでPythonの辞書に変換する
            result = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        else:
            # 通常モード: RSS取得 → AI要約 の順に実行する
            print(f"[{edition}] ニュース取得中...")
            articles = fetch_all(hours=args.hours, candidate_factor=CANDIDATE_FACTOR)

            if not articles:
                print("対象記事が見つかりませんでした。")
                sys.exit(0)

            # カテゴリごとの記事数を集計して表示
            total = sum(len(v) for v in articles.values())
            print(f"  取得: {total}件（{len(articles)}カテゴリ）")
            articles = select(articles, load_category_limits())

            from summarizer import LLM_PROVIDER
            print(f"{LLM_PROVIDER.capitalize()} APIで要約中...")
            result = summarize(articles)
            # 次回 --use-cache で再利用できるよう、要約結果をJSONファイルに保存する
            # ensure_ascii=False で日本語をそのまま保存、indent=2 で読みやすく整形する
            CACHE_PATH.parent.mkdir(exist_ok=True)
            CACHE_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        # 要約の件数を表示して進捗を確認できるようにする
        print(f"  要約: {len(result.get('summaries', []))}件")

        # 注目銘柄に Yahoo の現在値・前日比をベストエフォートでマージする。
        # キャッシュ保存（上記 CACHE_PATH 書き込み）の後に実行するため、価格はキャッシュに残らない。
        result["stock_picks"] = enrich_stock_prices(result.get("stock_picks", []))

        print("メール送信中..." if not args.dry_run else "（dry-run）メール内容を表示します")
        send(edition, result, dry_run=args.dry_run)
    except Exception as e:
        # 予期しないエラーが起きた場合は原因を表示してプログラムを終了する
        # sys.stderr はエラー専用の出力先で、通常の出力と分けることで問題の特定がしやすくなる
        # 例外メッセージ本文には smtplib 経由で送信元/送信先メアドが含まれ得るため、
        # ログには例外型名のみ出す（lambda_function.py / quotes.py と統一）
        print(f"エラーが発生しました: {type(e).__name__}", file=sys.stderr)
        sys.exit(1)


# このファイルを直接実行したときだけ main() を呼び出す
# 他のファイルから import された場合は実行しない（Pythonの慣習的な書き方）
if __name__ == "__main__":
    main()
