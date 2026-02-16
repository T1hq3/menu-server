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

UPDATE_INTERVAL = 1800  # 30 minutes

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

    # Повні headers як у робочому скрипті
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

    # Дуже важливо
    session.headers.update({"authorization": token})
    session.cookies.set("token", token)

    logging.info("Login successful")

    return session



# ======================
# DOWNLOAD EXCEL
# ======================

def download_excel(session):
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

    SECTION_ORDER = [
        "Сети", "Роли", "Кухня", "Ланчі 11:00-17:00",
        "Коктейльна карта", "Гарячі напої",
        "Безалкогольний бар", "Алкогольний бар", "Винна карта",
    ]

    def render_category(category, items):
        block = f'<div class="category"><div class="cat-header">{category}</div>'

        for _, row in items.iterrows():
            name = str(row.get("Dish name", "")).strip()
            desc = str(row.get("Description", "")).strip()
            price = str(row.get("Price", "")).strip()
            weight = str(row.get("Weight, g", "")).strip()

            if price == "0":
                price = ""

            block += f'''
            <div class="item">
                <div class="item-top">
                    <span>{name}</span>
                    <span>{price}</span>
                </div>
            '''

            if desc:
                block += f'<div class="desc">{desc}</div>'

            if weight and weight.lower() != "nan":
                block += f'<div class="weight">{weight} г</div>'

            block += '</div>'

        block += '</div>'
        return block

    html = """
    <html>
    <head>
    <meta charset="utf-8">
    <style>
    @page { size: A4; margin: 25px 35px; }
    body { font-family: DejaVu Sans, sans-serif; }

    .section { margin-bottom: 40px; }
    h1 { text-align: center; font-size: 28px; margin-bottom: 25px; }

    .columns { display: flex; gap: 30px; }
    .column { flex: 1; }

    .category {
        margin-bottom: 20px;
        border: 2px solid #333;
        border-radius: 10px;
        padding: 14px 16px;
        page-break-inside: avoid;
    }

    .cat-header {
        font-size: 20px;
        font-weight: 700;
        margin-bottom: 12px;
    }

    .item { margin-bottom: 8px; }

    .item-top {
        display: flex;
        justify-content: space-between;
        border-bottom: 1px dotted #777;
        padding-bottom: 2px;
    }

    .item-top span {
        font-weight: 700;
        font-size: 14px;
    }

    .desc { font-size: 10px; color: #444; margin-top: 2px; }
    .weight { font-size: 9px; color: #666; }

    </style>
    </head>
    <body>
    """

    for section in SECTION_ORDER:
        section_df = df[df["Section"] == section]
        if section_df.empty:
            continue

        html += f'<div class="section"><h1>{section}</h1>'
        html += '<div class="columns"><div class="column">'

        for category, items in section_df.groupby("Category"):
            html += render_category(category, items)

        html += '</div></div></div>'

    html += "</body></html>"
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
    <body style="text-align:center;margin-top:100px;">
        <h1>Restaurant Menu</h1>
        <a href="/download">Download PDF</a><br><br>
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
