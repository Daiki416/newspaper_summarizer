# このファイルはメール本文の組み立てと送信を担当します。
# テキスト形式とHTML形式の2種類を作り、メールクライアントに応じて
# 適切な方が表示されるようにします。

import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

# 日本標準時（UTC+9）の定義
JST = timezone(timedelta(hours=9))

# カテゴリ名に対応するアイコン絵文字の対応表
# dict.get() でカテゴリ名をキーとして検索し、なければ "📄" を使う
CATEGORY_ICONS = {
    "国内政治・経済": "🏛",
    "国内ビジネス": "📈",
    "国内投資・マーケット": "💹",
    "国内テクノロジー・科学": "🔬",
    "国際": "🌐",
}


def _build_text(edition: str, result: dict, date_str: str) -> str:
    """プレーンテキスト形式のメール本文を組み立てる。

    HTMLが表示できないメールクライアントや、スクリーンリーダーのために
    テキストのみの版も用意する。
    """
    # lines リストに行を追加して最後に改行で結合する方式にすると
    # 長い文字列の連結より効率的でコードも読みやすい
    lines = [f"📰 [{edition}] {date_str} 主要ニュース", ""]

    # 記事要約セクション
    for item in result.get("summaries", []):
        cat = item.get("category", "")
        icon = CATEGORY_ICONS.get(cat, "📄")
        lines.append(f"━━ {icon} {cat} ━━")
        lines.append(f"【{item['title']}】")
        lines.append(item["summary"])
        lines.append(f"🔗 {item['url']}")
        lines.append(f"📰 {item.get('source', '')}")
        lines.append("")

    # 生活への影響セクション（内容がある場合のみ表示）
    life_impact = result.get("life_impact", "")
    if life_impact:
        lines.append("━━ 🏠 生活への影響 ━━")
        lines.append(life_impact)
        lines.append("")

    # 用語解説セクション（用語がある場合のみ表示）
    terms = result.get("terms", [])
    if terms:
        lines.append("━━ 📚 今日の用語 ━━")
        for t in terms:
            # 読み仮名がある場合は [] で囲んで表示する、ない場合は空文字
            reading = f"[{t['reading']}]" if t.get("reading") else ""
            lines.append(f"• {t['word']}{reading}")
            lines.append(f"  {t['explanation']}")
        lines.append("")

    # 注目銘柄候補セクション（銘柄がある場合のみ表示）
    stock_picks = result.get("stock_picks", [])
    if stock_picks:
        lines.append("━━ 📊 注目銘柄候補 ━━")
        lines.append("※投資判断はご自身の責任でお願いします")
        for s in stock_picks:
            lines.append(f"• {s['ticker']} {s['name']} {s['direction']}")
            lines.append(f"  {s['reason']}")
            lines.append(f"  根拠: {s['source_headline']}")
        lines.append("")

    return "\n".join(lines)


def _build_html(edition: str, result: dict, date_str: str) -> str:
    """HTML形式のメール本文を組み立てる。

    HTMLメールはブラウザと同様にタグで見た目を整えられる。
    ただしテキストをそのままHTMLに埋め込むと、「<」「>」「&」などの
    特殊文字がHTMLタグと誤認される危険があるため、html.escape() で
    安全な文字列（例: & → &amp;）に変換してから埋め込む。
    これを「HTMLエスケープ」と呼ぶ。
    """
    # HTMLの骨格とCSSスタイルを先に定義する
    # parts リストに文字列を追加して最後に join() で結合するのが効率的
    parts = [
        "<!DOCTYPE html><html><head>",
        '<meta charset="utf-8">',
        '<style>',
        # メール本文の基本スタイル（フォント・幅・余白・文字色・行間）
        "body{font-family:'Hiragino Sans','Meiryo',sans-serif;max-width:640px;margin:0 auto;padding:16px;color:#222;line-height:1.7}",
        "h1{font-size:1.2em;border-bottom:2px solid #333;padding-bottom:8px}",
        "h2{font-size:1em;background:#f4f4f4;padding:6px 10px;border-left:4px solid #555;margin-top:24px}",
        ".article{margin:12px 0 20px}",
        ".article-title{font-weight:bold}",
        ".article-summary{margin:4px 0}",
        "a{color:#1a73e8;text-decoration:none}",
        ".terms{background:#fffbe6;border:1px solid #f0d060;padding:12px 16px;margin-top:24px;border-radius:6px}",
        ".terms h2{background:none;border:none;padding:0;margin:0 0 8px}",
        ".term{margin:8px 0}.term-word{font-weight:bold}",
        ".life-impact{background:#e8f4e8;border:1px solid #60c060;padding:12px 16px;margin-top:24px;border-radius:6px}",
        ".stocks{background:#e8f0fe;border:1px solid #6090d0;padding:12px 16px;margin-top:16px;border-radius:6px}",
        ".stock-item{margin:10px 0}.stock-meta{font-weight:bold}.stock-disclaimer{font-size:0.85em;color:#666;margin-bottom:8px}",
        ".article-source{font-size:0.8em;color:#888;margin-top:2px}",
        "</style></head><body>",
        f"<h1>📰 [{edition}] {date_str} 主要ニュース</h1>",
    ]

    # 記事要約セクション
    for item in result.get("summaries", []):
        cat = item.get("category", "")
        icon = CATEGORY_ICONS.get(cat, "📄")
        # html.escape() でHTMLエスケープ（特殊文字をHTMLの表示文字に変換）
        safe_cat = html.escape(cat)
        safe_title = html.escape(item["title"])
        safe_summary = html.escape(item["summary"])
        url = item["url"]
        # URLに不正な値が入ってもリンクが安全になるよう、https/http 以外は # に置き換える
        # quote=True にすると URL の中の & なども安全にエスケープされる
        safe_url = html.escape(url, quote=True) if url.startswith(("https://", "http://")) else "#"
        parts.append(f"<h2>{icon} {safe_cat}</h2>")
        parts.append('<div class="article">')
        parts.append(f'<div class="article-title">{safe_title}</div>')
        parts.append(f'<div class="article-summary">{safe_summary}</div>')
        parts.append(f'<a href="{safe_url}">🔗 記事を読む</a>')
        parts.append(f'<div class="article-source">📰 {html.escape(item.get("source", ""))}</div>')
        parts.append("</div>")

    # 生活への影響セクション
    life_impact = result.get("life_impact", "")
    if life_impact:
        parts.append('<div class="life-impact"><h2>🏠 生活への影響</h2>')
        parts.append(f'<p>{html.escape(life_impact)}</p>')
        parts.append("</div>")

    # 用語解説セクション
    terms = result.get("terms", [])
    if terms:
        parts.append('<div class="terms"><h2>📚 今日の用語</h2>')
        for t in terms:
            # 読み仮名がある場合は（よみ）形式で表示、ない場合は空文字
            reading = f"（{html.escape(t['reading'])}）" if t.get("reading") else ""
            parts.append('<div class="term">')
            parts.append(f'<span class="term-word">{html.escape(t["word"])}{reading}</span><br>')
            parts.append(f'{html.escape(t["explanation"])}')
            parts.append("</div>")
        parts.append("</div>")

    # 注目銘柄候補セクション
    stock_picks = result.get("stock_picks", [])
    if stock_picks:
        parts.append('<div class="stocks"><h2>📊 注目銘柄候補</h2>')
        parts.append('<div class="stock-disclaimer">※投資判断はご自身の責任でお願いします</div>')
        for s in stock_picks:
            parts.append('<div class="stock-item">')
            parts.append(f'<div class="stock-meta">{html.escape(s["ticker"])} {html.escape(s["name"])} {html.escape(s["direction"])}</div>')
            parts.append(f'<div>{html.escape(s["reason"])}</div>')
            parts.append(f'<div>根拠: {html.escape(s["source_headline"])}</div>')
            parts.append("</div>")
        parts.append("</div>")

    parts.append("</body></html>")
    # 全パーツを結合して1つのHTML文字列として返す
    return "".join(parts)


def _mask_email(email: str) -> str:
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    return f"{local[0]}***@{domain}"


def send(edition: str, result: dict, dry_run: bool = False) -> None:
    """要約結果をメールで送信する。

    Args:
        edition: "朝刊" or "夕刊"
        result: summarize() の返り値
        dry_run: True のとき実際には送信せずテキストを標準出力
    """
    now_jst = datetime.now(JST)
    date_str = f"{now_jst.year}年{now_jst.month}月{now_jst.day}日"
    subject = f"📰 [{edition}] {date_str} 主要ニュース"

    # テキスト版とHTML版の両方を作る（メールクライアントが選んで表示する）
    text_body = _build_text(edition, result, date_str)
    html_body = _build_html(edition, result, date_str)

    if dry_run:
        # --dry-run 指定時は実際に送らず内容だけターミナルに表示する
        print("=" * 60)
        print(f"件名: {subject}")
        print("=" * 60)
        print(text_body)
        return

    # --- 環境変数のチェック ---
    # 送信に必要な設定が .env に揃っているか確認する
    # 不足している場合はわかりやすいエラーメッセージを出して終了する
    required_vars = ["GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "NOTIFY_EMAIL"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        raise SystemExit(f"必須の環境変数が設定されていません: {', '.join(missing)}")

    gmail_address = os.environ["GMAIL_ADDRESS"]
    # アプリパスワードはGmailの通常パスワードではなく、
    # Googleアカウントで発行した16桁の専用パスワード（2段階認証が必要）
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    # カンマ区切りで複数アドレスを指定可能（例: a@gmail.com,b@gmail.com）
    recipients = [e.strip() for e in os.environ["NOTIFY_EMAIL"].split(",") if e.strip()]
    if not recipients:
        raise SystemExit("NOTIFY_EMAIL に有効なアドレスが含まれていません")

    # --- メールの組み立て ---
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = gmail_address
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.starttls()
        server.login(gmail_address, app_password)
        server.sendmail(gmail_address, recipients, msg.as_string())

    masked = ", ".join(_mask_email(e) for e in recipients)
    print(f"送信完了: {subject} → {masked}")
