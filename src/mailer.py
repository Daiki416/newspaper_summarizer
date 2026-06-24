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


def _format_price_line(stock: dict) -> str | None:
    """注目銘柄の現在値・前日比を表す文言を返す。price が無ければ None。

    例: "現在値 2,750円（前日比 +1.8%）"。
    Yahoo chart API の regularMarketPrice（現在値）ベースのため「現在値」と書く。
    符号: 正は "+1.8%"、負は "-0.5%"、ゼロは "±0.0%"。
    """
    price = stock.get("price")
    if price is None:
        return None
    pct = stock.get("change_pct", 0.0)
    if pct > 0:
        pct_str = f"+{pct:.1f}%"
    elif pct < 0:
        pct_str = f"{pct:.1f}%"  # マイナス符号は f-string が付与する
    else:
        pct_str = "±0.0%"
    return f"現在値 {price:,.0f}円（前日比 {pct_str}）"


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
        # 背景（記事ごと・内容がある場合のみ表示）
        background = item.get("background", "")
        if background:
            lines.append(f"🔍 背景: {background}")
        # 企業紹介（記事ごと・内容がある場合のみ表示）
        companies = item.get("companies", [])
        if companies:
            lines.append("🏢 企業紹介:")
            for c in companies:
                lines.append(f"• {c.get('name', '')} — {c.get('description', '')}")
        # 人物紹介（記事ごと・内容がある場合のみ表示）
        people = item.get("people", [])
        if people:
            lines.append("👤 人物紹介:")
            for p in people:
                lines.append(f"• {p.get('name', '')} — {p.get('description', '')}")
        # キーワード（記事ごと・内容がある場合のみ表示）
        keywords = item.get("keywords", [])
        if keywords:
            lines.append("🏷 キーワード:")
            for kw in keywords:
                lines.append(f"• {kw.get('word', '')} — {kw.get('note', '')}")
        lines.append(f"🔗 {item['url']}")
        lines.append(f"📰 {item.get('source', '')}")
        lines.append("")

    # 生活への影響セクション（全体で1個・内容がある場合のみ表示）
    life_impact = result.get("life_impact", "")
    if life_impact:
        lines.append("━━ 🏠 生活への影響 ━━")
        lines.append(life_impact)
        lines.append("")

    # 注目銘柄候補セクション（銘柄がある場合のみ表示）
    stock_picks = result.get("stock_picks", [])
    if stock_picks:
        lines.append("━━ 📊 注目銘柄候補 ━━")
        lines.append("※投資判断はご自身の責任でお願いします")
        for s in stock_picks:
            lines.append(f"• {s['ticker']} {s['name']} {s['direction']}")
            lines.append(f"  {s['reason']}")
            # 現在値・前日比（取得できた銘柄のみ・reason と根拠の間に表示）
            price_line = _format_price_line(s)
            if price_line:
                lines.append(f"  {price_line}")
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
        ".article-background{margin:4px 0;color:#555}",
        ".article-entities{margin:4px 0;font-size:0.9em}.article-entities .ent{margin:2px 0}.article-entities .ent-name{font-weight:bold}",
        ".life{margin:16px 0;background:#e8f4e8;border-left:4px solid #60c060;padding:8px 12px}",
        ".article-keywords{margin:4px 0;font-size:0.9em}.article-keywords .kw{margin:2px 0}.article-keywords .kw-word{font-weight:bold}",
        ".stocks{background:#e8f0fe;border:1px solid #6090d0;padding:12px 16px;margin-top:16px;border-radius:6px}",
        ".stock-item{margin:10px 0}.stock-meta{font-weight:bold}.stock-disclaimer{font-size:0.85em;color:#666;margin-bottom:8px}",
        ".stock-price{font-size:0.95em;color:#1a4d8f;margin:2px 0}",
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
        # 背景（記事ごと・内容がある場合のみ表示）
        background = item.get("background", "")
        if background:
            parts.append(f'<div class="article-background">🔍 背景: {html.escape(background)}</div>')
        # 企業紹介（記事ごと・内容がある場合のみ表示）
        companies = item.get("companies", [])
        if companies:
            parts.append('<div class="article-entities">🏢 企業紹介:')
            for c in companies:
                parts.append(
                    f'<div class="ent"><span class="ent-name">{html.escape(c.get("name", ""))}</span> — {html.escape(c.get("description", ""))}</div>'
                )
            parts.append("</div>")
        # 人物紹介（記事ごと・内容がある場合のみ表示）
        people = item.get("people", [])
        if people:
            parts.append('<div class="article-entities">👤 人物紹介:')
            for p in people:
                parts.append(
                    f'<div class="ent"><span class="ent-name">{html.escape(p.get("name", ""))}</span> — {html.escape(p.get("description", ""))}</div>'
                )
            parts.append("</div>")
        # キーワード（記事ごと・内容がある場合のみ表示）
        keywords = item.get("keywords", [])
        if keywords:
            parts.append('<div class="article-keywords">🏷 キーワード:')
            for kw in keywords:
                parts.append(
                    f'<div class="kw"><span class="kw-word">{html.escape(kw.get("word", ""))}</span> — {html.escape(kw.get("note", ""))}</div>'
                )
            parts.append("</div>")
        parts.append(f'<a href="{safe_url}">🔗 記事を読む</a>')
        parts.append(f'<div class="article-source">📰 {html.escape(item.get("source", ""))}</div>')
        parts.append("</div>")

    # 生活への影響セクション（全体で1個・内容がある場合のみ表示）
    life_impact = result.get("life_impact", "")
    if life_impact:
        parts.append(f'<div class="life"><h2>🏠 生活への影響</h2>{html.escape(life_impact)}</div>')

    # 注目銘柄候補セクション
    stock_picks = result.get("stock_picks", [])
    if stock_picks:
        parts.append('<div class="stocks"><h2>📊 注目銘柄候補</h2>')
        parts.append('<div class="stock-disclaimer">※投資判断はご自身の責任でお願いします</div>')
        for s in stock_picks:
            parts.append('<div class="stock-item">')
            parts.append(f'<div class="stock-meta">{html.escape(s["ticker"])} {html.escape(s["name"])} {html.escape(s["direction"])}</div>')
            parts.append(f'<div>{html.escape(s["reason"])}</div>')
            # 現在値・前日比（取得できた銘柄のみ）。整形後の文字列も html.escape する
            price_line = _format_price_line(s)
            if price_line:
                parts.append(f'<div class="stock-price">{html.escape(price_line)}</div>')
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
