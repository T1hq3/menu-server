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
        name = html.escape(str(row.get("Dish name", "")).strip())
        desc = html.escape(str(row.get("Description", "")).strip())
        price = html.escape(str(row.get("Price", "")).strip())
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

        return f"""
        <div class="item">
            <div class="item-top">
                <span class="dish-name">{name}</span>
                <span class="price">{price}</span>
            </div>
            {meta_html}
            {desc_html}
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
                <tr class="item-row">
                    <td>{render_item(row)}</td>
                </tr>
            """

        block += """
            </tbody>
        </table>
        """

        return block

    html_content = """
    <html>
    <head>
    <meta charset="utf-8">
    <style>
    @page {
        size: A4;
        margin: 8mm 8mm;

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
        min-height: calc(297mm - 16mm);
        display: flex;
        align-items: center;
        justify-content: center;
    }

    .cover-card {
        width: 100%;
        border: 1px solid #111;
        border-radius: 10px;
        text-align: center;
        padding: 14px 10px;
        background: linear-gradient(180deg, #ffffff 0%, #f1f1f1 100%);
    }

    .menu-brand {
        font-size: 46px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 2px;
        line-height: 1;
        margin-bottom: 10px;
    }

    .menu-subbrand {
        font-size: 14px;
        font-weight: 700;
        color: #444;
        text-transform: uppercase;
        letter-spacing: 1px;
    }

    .section-page {
        page-break-before: always;
    }

    .section-page:first-of-type {
        page-break-before: auto;
    }

    .section-title {
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
    }

    .menu-columns {
        column-count: 2;
        column-gap: 6mm;
    }

    .category-card {
        width: 100%;
        border: 1px solid #8f8f8f;
        border-radius: 5px;
        margin: 0 0 4px 0;
        border-collapse: separate;
        border-spacing: 0;
        break-inside: auto;
        page-break-inside: auto;
        box-decoration-break: clone;
        -webkit-box-decoration-break: clone;
        background: #fff;
        overflow: hidden;
    }

    .category-card thead {
        display: table-header-group;
    }

    .category-card tbody {
        display: table-row-group;
    }

    .cat-header {
        font-size: 11px;
        font-weight: 900;
        text-transform: uppercase;
        margin: 0;
        letter-spacing: 0.4px;
        padding: 2px 4px;
        background: #f5f5f5;
        border-radius: 0;
        text-align: left;
    }

    .item-row {
        break-inside: avoid;
        page-break-inside: avoid;
    }

    .item-row td {
        padding: 0 5px;
    }

    .item-row:first-child td {
        padding-top: 4px;
    }

    .item-row:last-child td {
        padding-bottom: 4px;
    }

    .item {
        margin-bottom: 4px;
        break-inside: avoid;
    }

    .item-meta {
        font-size: 8px;
        color: #666;
        margin-top: 1px;
        line-height: 1.15;
    }

    .item-desc {
        font-size: 7.6px;
        color: #555;
        line-height: 1.15;
        margin-top: 1px;
    }

    .item:last-child {
        margin-bottom: 1px;
    }

    .item-top {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 8px;
    }

    .dish-name {
        font-size: 10.6px;
        font-weight: 700;
        line-height: 1.15;
    }

    .price {
        font-size: 10.2px;
        font-weight: 700;
        white-space: nowrap;
    }

    .item-top:last-child {
        border-bottom: none;
    }

    .menu-columns,
    .item {
        orphans: 2;
        widows: 2;
    }

    .menu-columns {
        column-fill: auto;
        min-height: 0;
    }

    </style>
    </head>
    <body>
        <section class="cover-page">
            <div class="cover-card">
                <div class="menu-brand">Sunrise Menu</div>
                <div class="menu-subbrand">Офіційне меню ресторану Sunrise</div>
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

def generate_menu_pdf():
    if not os.path.exists(EXCEL_FILE):
        raise Exception("Excel missing")

    df = pd.read_excel(EXCEL_FILE)
    required_columns = ["Section", "Category", "Dish name", "Description", "Price", "Weight, g"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise Exception(f"Excel missing required columns: {', '.join(missing_columns)}")

    df = df[df["Section"].notna()]
    df = df.fillna("")

    html_content = build_html(df)

    if os.path.exists(PDF_FILE):
        os.remove(PDF_FILE)

    try:
        HTML(string=html_content).write_pdf(PDF_FILE)
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
            <h1>Sunrise Menu</h1>
            <div class="subtitle">Офіційне меню ресторану Sunrise</div>

            <form action="/download" method="get" style="margin-bottom:6px;">
                <button type="submit" class="download-btn">
                    Завантажити актуальний PDF
                </button>
            </form>

            <a href="/status" class="link">Статус системи</a>
        </div>
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
