#!/bin/bash
# cron ジョブを登録するスクリプト
# 実行前に .env ファイルを作成してください: cp .env.example .env

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
MAIN="$SCRIPT_DIR/src/main.py"
LOG_DIR="$SCRIPT_DIR/logs"

mkdir -p "$LOG_DIR"

# 既存の newspaper エントリを除去して再登録
EXISTING=$(crontab -l 2>/dev/null | grep -v "# newspaper")
NEW_ENTRIES="$EXISTING
# newspaper: 朝刊 (毎朝7時)
0 7 * * * cd \"$SCRIPT_DIR\" && \"$PYTHON\" \"$MAIN\" --time morning >> \"$LOG_DIR/morning.log\" 2>&1
# newspaper: 夕刊 (毎夕19時)
0 19 * * * cd \"$SCRIPT_DIR\" && \"$PYTHON\" \"$MAIN\" --time evening >> \"$LOG_DIR/evening.log\" 2>&1"

echo "$NEW_ENTRIES" | crontab -

echo "✅ cron ジョブを登録しました"
echo ""
echo "登録内容:"
crontab -l | grep newspaper
echo ""
echo "ログファイル: $LOG_DIR/"
echo ""
echo "【次のステップ】"
echo "1. .env ファイルを作成: cp .env.example .env"
echo "2. .env を編集して API キーとメールアドレスを設定"
echo "3. 依存パッケージをインストール: pip install -r requirements.txt"
echo "4. 動作確認: python src/main.py --time morning --dry-run"
