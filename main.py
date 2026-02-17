from flask import Flask, send_file, render_template_string, jsonify
import requests
import time
import threading
import os
import pandas as pd
from weasyprint import HTML
from datetime import datetime, timedelta
import logging

# ======================
# CONFIG
# ======================

app = Flask(__name__)

IDENTIFIER = os.getenv("IDENTIFIER")
PASSWORD = os.getenv("PASSWORD")

LOGIN_URL = "https://sunrise.choiceqr.com/api/auth/local"
EXPORT_URL = "https://sunrise.choiceqr.com/api/export/xlsx"

SAVE_PATH = "./exports"
EXCEL_FILE = f"{SAVE_PATH}/menu.xlsx"
PDF_FILE = f"{SAVE_PATH}/menu.pdf"

UPDATE_INTERVAL = 7200  # 2 hours

update_lock = threading.Lock()

STATUS = {
    "last_update": None,
    "next_update": None,
    "excel_downloaded": False,
    "pdf_generated": False,
    "pdf_ready": False,
    "countdown": 0,
    "error": None
}

# ======================
# LOGGING
# ======================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ======================
# LOGIN
# ======================

def login_and_get_session():
    if not IDENTIFIER or not PASSWORD:
        raise Exception("ENV variables missing")

    session = requests.Session()

    session.headers.update({
        "accept": "*/*",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": "https://sunrise.choiceqr.com/admin/"
    })

    logging.info("Sending login request...")

    response = session.post(
        LOGIN_URL,
        json={
            "identifier": IDENTIFIER,
            "password": PASSWORD
        },
        timeout=15
    )

    logging.info(f"Login status: {response.status_code}")

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

    logging.info("Login successful")

    return session


# ======================
# DOWNLOAD EXCEL
# ======================

def download_excel(session):
    if os.path.exists(EXCEL_FILE):
        os.remove(EXCEL_FILE)

    response = session.get(EXPORT_URL, timeout=30)

    if response.status_code != 200:
        raise Exception(f"Excel download failed: {response.status_code}")

    with open(EXCEL_FILE, "wb") as f:
        f.write(response.content)

    if not os.path.exists(EXCEL_FILE) or os.path.getsize(EXCEL_FILE) == 0:
        raise Exception("Excel file corrupted")

    STATUS["excel_downloaded"] = True
    logging.info("✔ Excel downloaded")


# ======================
# HTML BUILDER
# ======================

def build_html(df):

    section_order = [
        "Сети", "Роли", "Кухня", "Ланчі 11:00-17:00",
        "Коктейльна карта", "Гарячі напої",
        "Безалкогольний бар", "Алкогольний бар", "Винна карта",
    ]

    def render_item(row):
        name = str(row.get("Dish name", "")).strip()
        desc = str(row.get("Description", "")).strip()
        price = str(row.get("Price", "")).strip()
        weight = str(row.get("Weight, g", "")).strip()

        if price == "0":
            price = ""

        meta = []
        if weight and weight.lower() != "nan":
            meta.append(f"{weight} г")

        meta_html = ""
        if meta:
            meta_html = f'<div class="item-meta">{" • ".join(meta)}</div>'

        desc_html = f'<div class="item-desc">{desc}</div>' if desc else ""

        return f'''
        <div class="item">
            <div class="item-top">
                <span class="dish-name">{name}</span>
                <span class="price">{price}</span>
            </div>
            {meta_html}
            {desc_html}
        </div>
        '''

    def render_category(category, items):
        block = f'''
        <div class="category-card">
            <div class="cat-header">{category}</div>
        '''

        for _, row in items.iterrows():
            block += render_item(row)

        block += "</div>"
        return block

    html = """
    <html>
    <head>
    <meta charset="utf-8">
    <style>
    @page {
        size: A4;
        margin: 12mm 10mm;

        @bottom-center {
            content: counter(page);
            font-size: 8px;
            color: #777;
        }
    }

    body {
        font-family: "DejaVu Sans", sans-serif;
        color: #111;
        margin: 0;
        font-size: 10px;
    }

    .cover-page {
        page-break-after: always;
        min-height: 260mm;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        text-align: center;
    }

    .cover-title {
        font-size: 64px;
        font-weight: 900;
        letter-spacing: 2px;
        text-transform: uppercase;
        line-height: 1;
        margin-bottom: 14px;
    }

    .cover-subtitle {
        font-size: 26px;
        font-weight: 700;
        letter-spacing: 1px;
        text-transform: uppercase;
        color: #333;
    }

    .menu-columns {
        column-count: 2;
        column-gap: 10mm;
    }

    .section-block {
        break-inside: avoid;
        margin: 0 0 8px 0;
    }

    .section-title {
        font-size: 15px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        text-align: center;
        margin: 0 0 7px 0;
        border: 1px solid #777;
        border-radius: 6px;
        padding: 4px 6px;
        background: #f2f2f2;
    }

    .category-card {
        border: 1px solid #888;
        border-radius: 6px;
        padding: 5px 6px;
        margin: 0 0 6px 0;
        break-inside: avoid;
        background: #fff;
    }

    .cat-header {
        font-size: 11px;
        font-weight: 800;
        text-transform: uppercase;
        margin-bottom: 5px;
    }

    .item {
        margin-bottom: 4px;
    }

    .item-top {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        border-bottom: 1px dotted #999;
        padding-bottom: 1px;
    }

    .dish-name {
        font-size: 10px;
        font-weight: 700;
        max-width: 78%;
    }

    .price {
        font-size: 10px;
        font-weight: 800;
        white-space: nowrap;
        margin-left: 8px;
    }

    .item-meta {
        font-size: 8px;
        color: #666;
        margin-top: 1px;
    }

    .item-desc {
        font-size: 7.5px;
        color: #555;
        line-height: 1.2;
        margin-top: 1px;
    }
    </style>
    </head>
    <body>
        <section class="cover-page">
            <div class="cover-title">Sunrise</div>
            <div class="cover-subtitle">Суші-бар</div>
        </section>

        <section class="menu-columns">
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
        html += f'''
        <div class="section-block">
            <div class="section-title">{section}</div>
        '''

        for category, items in section_df.groupby("Category", sort=False):
            html += render_category(category, items)

        html += "</div>"

    html += """
        </section>
    </body>
    </html>
    """

    return html


# ======================
# GENERATE PDF
# ======================

def generate_menu_pdf():
    if not os.path.exists(EXCEL_FILE):
        raise Exception("Excel missing")

    df = pd.read_excel(EXCEL_FILE)
    df = df[df["Section"].notna()]
    df = df.fillna("")

    html = build_html(df)

    if os.path.exists(PDF_FILE):
        os.remove(PDF_FILE)

    try:
        HTML(string=html).write_pdf(PDF_FILE)
    except Exception as e:
        raise Exception(f"PDF generation error: {str(e)}")

    if not os.path.exists(PDF_FILE) or os.path.getsize(PDF_FILE) == 0:
        raise Exception("PDF generation failed")

    STATUS["pdf_generated"] = True
    STATUS["pdf_ready"] = True
    logging.info("✔ PDF generated")


# ======================
# UPDATE MENU
# ======================

def update_menu():
    if not update_lock.acquire(blocking=False):
        logging.warning("Update already running")
        return

    logging.info("=== START UPDATE ===")

    STATUS.update({
        "error": None,
        "excel_downloaded": False,
        "pdf_generated": False,
        "pdf_ready": False
    })

    try:
        os.makedirs(SAVE_PATH, exist_ok=True)

        with login_and_get_session() as session:
            download_excel(session)

        generate_menu_pdf()

        STATUS["last_update"] = datetime.now()
        STATUS["next_update"] = datetime.now() + timedelta(seconds=UPDATE_INTERVAL)

        logging.info("=== UPDATE COMPLETE ===")

    except Exception as e:
        STATUS["error"] = str(e)
        logging.exception("Update failed")

    finally:
        update_lock.release()


# ======================
# ROUTES
# ======================

@app.route("/")
def index():
    return render_template_string("""
    <html>
    <body style="text-align:center;margin-top:100px;font-family:Arial,sans-serif;">
        <h1>Restaurant Menu</h1>

        <form action="/download" method="get" style="margin-bottom:20px;">
            <button type="submit" style="padding:12px 24px;font-size:16px;cursor:pointer;">
                Download Latest PDF
            </button>
        </form>

        <a href="/status">System Status</a>
    </body>
    </html>
    """)


@app.route("/download")
def download_pdf():
    if not STATUS["pdf_ready"]:
        return "PDF not ready yet", 503

    return send_file(
        PDF_FILE,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="menu.pdf"
    )


@app.route("/status")
def status():
    return jsonify({
        "last_update": str(STATUS["last_update"]),
        "next_update": str(STATUS["next_update"]),
        "countdown_seconds": STATUS["countdown"],
        "excel_downloaded": STATUS["excel_downloaded"],
        "pdf_generated": STATUS["pdf_generated"],
        "pdf_ready": STATUS["pdf_ready"],
        "error": STATUS["error"]
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
