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

UPDATE_INTERVAL = 1800  # 30 хвилин

STATUS = {
    "last_update": None,
    "next_update": None,
    "excel_downloaded": False,
    "pdf_generated": False,
    "pdf_ready": False,
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
# UPDATE MENU (DOWNLOAD + PDF)
# ======================

def update_menu():
    logging.info("=== START UPDATE ===")

    STATUS["error"] = None
    STATUS["excel_downloaded"] = False
    STATUS["pdf_generated"] = False
    STATUS["pdf_ready"] = False

    if not IDENTIFIER or not PASSWORD:
        STATUS["error"] = "ENV variables missing"
        logging.error("ENV variables missing")
        return

    os.makedirs(SAVE_PATH, exist_ok=True)

    session = requests.Session()

    try:
        # LOGIN
        login_res = session.post(
            LOGIN_URL,
            json={
                "identifier": IDENTIFIER,
                "password": PASSWORD
            },
            timeout=15
        )

        if login_res.status_code not in (200, 201):
            STATUS["error"] = f"Login failed: {login_res.status_code}"
            logging.error(STATUS["error"])
            return

        token = login_res.json().get("token")
        if not token:
            STATUS["error"] = "Token not received"
            logging.error("Token not received")
            return

        session.headers.update({"authorization": token})

        # DOWNLOAD EXCEL
        export_res = session.get(EXPORT_URL, timeout=30)

        if export_res.status_code != 200:
            STATUS["error"] = f"Excel download failed: {export_res.status_code}"
            logging.error(STATUS["error"])
            return

        with open(EXCEL_FILE, "wb") as f:
            f.write(export_res.content)

        if os.path.exists(EXCEL_FILE) and os.path.getsize(EXCEL_FILE) > 0:
            STATUS["excel_downloaded"] = True
            logging.info("✔ Excel downloaded")
        else:
            STATUS["error"] = "Excel file corrupted"
            return

        # GENERATE PDF
        generate_menu_pdf()

        if os.path.exists(PDF_FILE) and os.path.getsize(PDF_FILE) > 0:
            STATUS["pdf_generated"] = True
            STATUS["pdf_ready"] = True
            logging.info("✔ PDF generated and ready")
        else:
            STATUS["error"] = "PDF generation failed"

        # TIME TRACKING
        STATUS["last_update"] = datetime.now()
        STATUS["next_update"] = datetime.now() + timedelta(seconds=UPDATE_INTERVAL)

        logging.info("=== UPDATE COMPLETE ===")

    except Exception as e:
        STATUS["error"] = str(e)
        logging.exception("Critical error")


# ======================
# HTML BUILDER
# ======================

def build_html(df):

    SECTION_ORDER = [
        "Сети",
        "Роли",
        "Кухня",
        "Ланчі 11:00-17:00",
        "Коктейльна карта",
        "Гарячі напої",
        "Безалкогольний бар",
        "Алкогольний бар",
        "Винна карта",
    ]

    html = """
    <html>
    <head>
    <meta charset="utf-8">
    <style>
    @page { size: A4; margin: 25px 35px; }
    body { font-family: DejaVu Sans, sans-serif; }
    .section { page-break-before: always; }
    .section:first-child { page-break-before: auto; }
    h1 { text-align: center; font-size: 28px; margin-bottom: 25px; font-weight: 700; }
    .columns { column-count: 2; column-gap: 35px; }
    .category { break-inside: avoid; margin-bottom: 20px; border: 2px solid #333; border-radius: 10px; padding: 14px 16px; }
    .cat-header { font-size: 20px; font-weight: 700; margin-bottom: 12px; }
    .item { margin-bottom: 8px; }
    .item-top { display: flex; justify-content: space-between; border-bottom: 1px dotted #777; padding-bottom: 2px; }
    .item-top span { font-weight: 700; font-size: 14px; }
    .desc { font-size: 10px; color: #444; margin-top: 2px; line-height: 1.2; }
    .weight { font-size: 9px; color: #666; }
    </style>
    </head>
    <body>
    """

    for section in SECTION_ORDER:
        section_df = df[df["Section"] == section]
        if section_df.empty:
            continue

        html += f'<div class="section"><h1>{section}</h1><div class="columns">'

        for category, items in section_df.groupby("Category"):
            html += f'<div class="category"><div class="cat-header">{category}</div>'

            for _, row in items.iterrows():
                name = str(row.get("Dish name", "")).strip()
                desc = str(row.get("Description", "")).strip()
                price = str(row.get("Price", "")).strip()
                weight = str(row.get("Weight, g", "")).strip()

                if price == "0":
                    price = ""

                html += f'''
                <div class="item">
                    <div class="item-top">
                        <span>{name}</span>
                        <span>{price}</span>
                    </div>
                '''

                if desc:
                    html += f'<div class="desc">{desc}</div>'
                if weight and weight.lower() != "nan":
                    html += f'<div class="weight">{weight} г</div>'

                html += '</div>'

            html += '</div>'

        html += '</div></div>'

    html += "</body></html>"
    return html


# ======================
# PDF GENERATION
# ======================

def generate_menu_pdf():

    if not os.path.exists(EXCEL_FILE):
        STATUS["error"] = "Excel missing"
        return

    df = pd.read_excel(EXCEL_FILE)
    df = df[df["Section"].notna()]
    df = df.fillna("")

    html = build_html(df)
    HTML(string=html).write_pdf(PDF_FILE)

    logging.info("✔ MENU PDF GENERATED")


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
        "excel_downloaded": STATUS["excel_downloaded"],
        "pdf_generated": STATUS["pdf_generated"],
        "pdf_ready": STATUS["pdf_ready"],
        "error": STATUS["error"]
    })


# ======================
# BACKGROUND WORKER
# ======================

def background_worker():
    while True:
        update_menu()

        for i in range(UPDATE_INTERVAL, 0, -1):
            mins = i // 60
            secs = i % 60
            print(f"Next update in: {mins:02d}:{secs:02d}", end="\r")
            time.sleep(1)


# ======================
# START
# ======================

if __name__ == "__main__":

    t = threading.Thread(target=background_worker, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
