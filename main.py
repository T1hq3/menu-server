from flask import Flask, send_file, render_template_string, jsonify
import requests
import time
import threading
import os
import html
import pandas as pd
from weasyprint import HTML
from datetime import datetime, timedelta
import logging

# ======================
# CONFIG
# ======================

app = Flask(__name__)

SAVE_PATH = "./exports"

VENUES = {
    "sunrise": {
        "name": "Sunrise",
        "subbrand": "Офіційне меню ресторану Sunrise",
        "identifier": os.getenv("SUNRISE_IDENTIFIER") or os.getenv("IDENTIFIER"),
        "password": os.getenv("SUNRISE_PASSWORD") or os.getenv("PASSWORD"),
        "login_url": "https://sunrise.choiceqr.com/api/auth/local",
        "export_url": "https://sunrise.choiceqr.com/api/export/xlsx",
        "referer": "https://sunrise.choiceqr.com/admin/",
    },
    "babuin": {
        "name": "BABUIN",
        "subbrand": "Офіційне меню ресторану BABUIN",
        "identifier": os.getenv("BABUIN_IDENTIFIER"),
        "password": os.getenv("BABUIN_PASSWORD"),
        "login_url": "https://babuin.choiceqr.com/api/auth/local",
        "export_url": "https://babuin.choiceqr.com/api/export/xlsx",
        "referer": "https://babuin.choiceqr.com/admin/",
    },
}

UPDATE_INTERVAL = 7200  # 2 hours

update_lock = threading.Lock()

STATUS = {
    "last_update": None,
    "next_update": None,
    "countdown": 0,
    "venues": {
        key: {
            "excel_downloaded": False,
            "pdf_generated": False,
            "pdf_ready": False,
            "error": None,
        }
        for key in VENUES
    }
}


# ======================
# LOGGING
# ======================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def venue_paths(venue_key):
    venue_dir = os.path.join(SAVE_PATH, venue_key)
    return {
        "dir": venue_dir,
        "excel": os.path.join(venue_dir, "menu.xlsx"),
        "pdf": os.path.join(venue_dir, "menu.pdf"),
    }


# ======================
# LOGIN
# ======================

def login_and_get_session(venue_key):
    venue = VENUES[venue_key]

    if not venue["identifier"] or not venue["password"]:
        raise Exception("ENV variables missing")

    session = requests.Session()

    session.headers.update({
        "accept": "*/*",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": venue["referer"],
    })

    logging.info(f"[{venue_key}] Sending login request...")

    response = session.post(
        venue["login_url"],
        json={
            "identifier": venue["identifier"],
            "password": venue["password"],
        },
        timeout=15
    )

    logging.info(f"[{venue_key}] Login status: {response.status_code}")

    if response.status_code not in (200, 201):
        raise Exception(f"Login failed: {response.status_code} | {response.text}")

    try:
        data = response.json()
        token = data.get("token")
    except Exception:
        raise Exception("Invalid login response")

    if not token:
        raise Exception("Token not received")

    session.headers.update({"authorization": token})
    session.cookies.set("token", token)

    logging.info(f"[{venue_key}] Login successful")

    return session


# ======================
# DOWNLOAD EXCEL
# ======================

def download_excel(session, venue_key):
    paths = venue_paths(venue_key)
    venue = VENUES[venue_key]

    if os.path.exists(paths["excel"]):
        os.remove(paths["excel"])

    response = session.get(venue["export_url"], timeout=30)

    if response.status_code != 200:
        raise Exception(f"Excel download failed: {response.status_code}")

    with open(paths["excel"], "wb") as f:
        f.write(response.content)

    if not os.path.exists(paths["excel"]) or os.path.getsize(paths["excel"]) == 0:
        raise Exception("Excel file corrupted")

    STATUS["venues"][venue_key]["excel_downloaded"] = True
    logging.info(f"[{venue_key}] ✔ Excel downloaded")


# ======================
# HTML BUILDER
# ======================

def build_html(df, venue_key):
    venue = VENUES[venue_key]

    section_order = [
        "Сети", "Роли", "Кухня", "Ланчі 11:00-17:00",
        "Коктейльна карта", "Гарячі напої",
        "Безалкогольний бар", "Алкогольний бар", "Винна карта",
    ]

    def render_item(row):
        name = html.escape(str(row.get("Dish name", "")).strip())
        desc = html.escape(str(row.get("Description", "")).strip())
        price = html.escape(str(row.get("Price", "")).strip())
        weight = str(row.get("Weight, g", "")).strip()

        if price == "0":
            price = ""

        desc_html = f'<div class="item-desc">{desc}</div>' if desc else ""
        weight_html = ""

        if weight and weight.lower() != "nan":
            weight_html = f'<div class="item-weight">{html.escape(weight)} г</div>'

        details_html = ""
        if desc_html or weight_html:
            details_html = f'''
            <div class="item-details">
                {desc_html}
                {weight_html}
            </div>
            '''

        price_html = ""
        if price:
            price_html = f'<span class="dots" aria-hidden="true"></span><span class="price">{price}</span>'

        return f"""
        <div class="item">
            <div class="item-top">
                <span class="dish-name">{name}</span>
                {price_html}
            </div>
            {details_html}
        </div>
        """

    def render_category(category, items):
        safe_category = html.escape(str(category).strip())
        block = f"""
        <table class="category-card">
            <thead>
                <tr>
                    <th class="cat-header">{safe_category}</th>
                </tr>
            </thead>
            <tbody>
        """

        for _, row in items.iterrows():
            block += f"""
            <tr>
                <td>{render_item(row)}</td>
            </tr>
            """

        block += """
            </tbody>
        </table>
        """

        return block

    html_content = f"""
    <html>
    <head>
    <meta charset="utf-8">
    <style>
    @page {{
        size: A4;
        margin: 8mm 8mm;

        @bottom-center {{
            content: counter(page);
            font-size: 8px;
            color: #777;
        }}
    }}

    body {{
        font-family: "DejaVu Sans", sans-serif;
        color: #111;
        margin: 0;
        font-size: 10px;
    }}

    .cover-page {{
        page-break-after: always;
        min-height: calc(297mm - 16mm);
        display: flex;
        align-items: center;
        justify-content: center;
    }}

    .cover-card {{
        width: 100%;
        border: 1px solid #111;
        border-radius: 10px;
        text-align: center;
        padding: 14px 10px;
        background: linear-gradient(180deg, #ffffff 0%, #f1f1f1 100%);
    }}

    .menu-brand {{
        font-size: 46px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 2px;
        line-height: 1;
        margin-bottom: 10px;
    }}

    .menu-subbrand {{
        font-size: 14px;
        font-weight: 700;
        color: #444;
        text-transform: uppercase;
        letter-spacing: 1px;
    }}

    .section-page {{
        page-break-before: always;
    }}

    .section-page:first-of-type {{
        page-break-before: auto;
    }}

    .section-title {{
        font-size: 16px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 1px;
        text-align: center;
        margin: 0 0 8px 0;
        border: 1px solid #555;
        border-radius: 6px;
        padding: 4px 8px;
        background: #ececec;
    }}

    .menu-columns {{
        column-count: 2;
        column-gap: 6mm;
    }}

    .category-card {{
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        border: 1px solid #8f8f8f;
        border-radius: 5px;
        padding: 4px 5px;
        margin: 0 0 4px 0;
        break-inside: auto;
        page-break-inside: auto;
        box-decoration-break: clone;
        -webkit-box-decoration-break: clone;
        background: #fff;
    }}

    .category-card thead {{
        display: table-header-group;
    }}

    .cat-header {{
        text-align: left;
        font-size: 11px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 0.4px;
        padding: 2px 4px;
        background: #f5f5f5;
        border-radius: 3px;
    }}

    .category-card td {{
        padding: 0;
    }}

    .item {{
        margin-bottom: 4px;
        break-inside: avoid;
    }}

    .item-desc {{
        font-size: 7.6px;
        color: #555;
        line-height: 1.15;
        margin-top: 1px;
        flex: 1 1 auto;
        min-width: 0;
    }}

    .item-details {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 8px;
    }}

    .item-weight {{
        font-size: 8px;
        color: #666;
        margin-top: 1px;
        line-height: 1.15;
        text-align: right;
        white-space: nowrap;
        flex: 0 0 auto;
    }}

    .item:last-child {{
        margin-bottom: 1px;
    }}

    .item-top {{
        display: flex;
        align-items: baseline;
        gap: 6px;
    }}

    .dots {{
        flex: 1 1 auto;
        border-bottom: 1px dotted #666;
        transform: translateY(-2px);
        min-width: 10px;
    }}

    .dish-name {{
        font-size: 10.6px;
        font-weight: 700;
        line-height: 1.15;
    }}

    .price {{
        font-size: 10.2px;
        font-weight: 700;
        white-space: nowrap;
    }}

    .item-top:last-child {{
        border-bottom: none;
    }}

    .menu-columns,
    .item {{
        orphans: 2;
        widows: 2;
    }}

    .menu-columns {{
        column-fill: auto;
        min-height: 0;
    }}

    </style>
    </head>
    <body>
        <section class="cover-page">
            <div class="cover-card">
                <div class="menu-brand">{html.escape(venue['name'])} Menu</div>
                <div class="menu-subbrand">{html.escape(venue['subbrand'])}</div>
            </div>
        </section>
    """

    ordered_df = []

    for section in section_order:
        section_df = df[df["Section"] == section]
        if not section_df.empty:
            ordered_df.append((section, section_df))

    remaining_sections = [s for s in df["Section"].dropna().unique().tolist() if s not in section_order]
    for section in remaining_sections:
        section_df = df[df["Section"] == section]
        if not section_df.empty:
            ordered_df.append((section, section_df))

    for section, section_df in ordered_df:
        safe_section = html.escape(str(section).strip())
        html_content += f"""
        <section class="section-page">
            <div class="section-title">{safe_section}</div>
            <div class="menu-columns">
        """

        for category, items in section_df.groupby("Category", sort=False):
            html_content += render_category(category, items)

        html_content += """
            </div>
        </section>
        """

    html_content += """
    </body>
    </html>
    """

    return html_content


# ======================
# GENERATE PDF
# ======================

def generate_menu_pdf(venue_key):
    paths = venue_paths(venue_key)

    if not os.path.exists(paths["excel"]):
        raise Exception("Excel missing")

    df = pd.read_excel(paths["excel"])
    required_columns = ["Section", "Category", "Dish name", "Description", "Price", "Weight, g"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise Exception(f"Excel missing required columns: {', '.join(missing_columns)}")

    df = df[df["Section"].notna()]
    df = df.fillna("")

    html_content = build_html(df, venue_key)

    if os.path.exists(paths["pdf"]):
        os.remove(paths["pdf"])

    try:
        HTML(string=html_content).write_pdf(paths["pdf"])
    except Exception as e:
        raise Exception(f"PDF generation error: {str(e)}")

    if not os.path.exists(paths["pdf"]) or os.path.getsize(paths["pdf"]) == 0:
        raise Exception("PDF generation failed")

    STATUS["venues"][venue_key]["pdf_generated"] = True
    STATUS["venues"][venue_key]["pdf_ready"] = True
    logging.info(f"[{venue_key}] ✔ PDF generated")


# ======================
# UPDATE MENU
# ======================

def update_venue_menu(venue_key):
    venue_status = STATUS["venues"][venue_key]
    venue_status.update({
        "error": None,
        "excel_downloaded": False,
        "pdf_generated": False,
        "pdf_ready": False,
    })

    paths = venue_paths(venue_key)
    os.makedirs(paths["dir"], exist_ok=True)

    with login_and_get_session(venue_key) as session:
        download_excel(session, venue_key)

    generate_menu_pdf(venue_key)


def update_menu():
    if not update_lock.acquire(blocking=False):
        logging.warning("Update already running")
        return

    logging.info("=== START UPDATE ===")

    try:
        os.makedirs(SAVE_PATH, exist_ok=True)

        for venue_key in VENUES:
            try:
                update_venue_menu(venue_key)
            except Exception as e:
                STATUS["venues"][venue_key]["error"] = str(e)
                logging.exception(f"[{venue_key}] Update failed")

        STATUS["last_update"] = datetime.now()
        STATUS["next_update"] = datetime.now() + timedelta(seconds=UPDATE_INTERVAL)

        logging.info("=== UPDATE COMPLETE ===")

    finally:
        update_lock.release()


# ======================
# ROUTES
# ======================

@app.route("/")
def index():
    return render_template_string("""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {
                margin: 0;
                min-height: 100vh;
                display: flex;
                align-items: center;
                justify-content: center;
                background: linear-gradient(160deg, #f6f6f6 0%, #e8e8e8 100%);
                font-family: Arial, sans-serif;
                color: #111;
            }

            .card {
                width: min(520px, 90vw);
                background: #fff;
                border: 1px solid #d4d4d4;
                border-radius: 16px;
                box-shadow: 0 8px 25px rgba(0, 0, 0, 0.08);
                padding: 30px 24px;
                text-align: center;
            }

            .subtitle {
                font-size: 13px;
                color: #666;
                margin-top: 4px;
                margin-bottom: 20px;
                text-transform: uppercase;
                letter-spacing: 0.7px;
            }

            .download-btn {
                border: none;
                background: #111;
                color: #fff;
                font-size: 16px;
                border-radius: 10px;
                padding: 12px 24px;
                cursor: pointer;
                font-weight: 700;
                width: 100%;
                margin-bottom: 10px;
            }

            .download-btn:hover {
                background: #2d2d2d;
            }

            .link {
                display: inline-block;
                margin-top: 16px;
                color: #3b3b3b;
                font-weight: 600;
            }
        </style>
    </head>
    <body>
        <div class="card">
            <h1>ChoiceQR Menu Export</h1>
            <div class="subtitle">Офіційні PDF меню закладів</div>

            <form action="/download/sunrise" method="get" style="margin-bottom:6px;">
                <button type="submit" class="download-btn">
                    Завантажити PDF — Sunrise
                </button>
            </form>

            <form action="/download/babuin" method="get" style="margin-bottom:6px;">
                <button type="submit" class="download-btn">
                    Завантажити PDF — BABUIN
                </button>
            </form>

            <a href="/status" class="link">Статус системи</a>
        </div>
    </body>
    </html>
    """)


@app.route("/download/<venue_key>")
def download_pdf(venue_key):
    if venue_key not in VENUES:
        return "Unknown venue", 404

    if not STATUS["venues"][venue_key]["pdf_ready"]:
        return "PDF not ready yet", 503

    paths = venue_paths(venue_key)

    return send_file(
        paths["pdf"],
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"menu-{venue_key}.pdf"
    )


@app.route("/status")
def status():
    return jsonify({
        "last_update": str(STATUS["last_update"]),
        "next_update": str(STATUS["next_update"]),
        "countdown_seconds": STATUS["countdown"],
        "venues": STATUS["venues"],
    })


# ======================
# BACKGROUND WORKER
# ======================

def background_worker():
    update_menu()  # first run immediately

    while True:
        for i in range(UPDATE_INTERVAL, 0, -1):
            STATUS["countdown"] = i
            time.sleep(1)

        update_menu()


# ======================
# START
# ======================

if __name__ == "__main__":
    t = threading.Thread(target=background_worker, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
