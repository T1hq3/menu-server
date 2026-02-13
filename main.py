from flask import Flask, send_file
import requests
import schedule
import time
import threading
import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
import pandas as pd

app = Flask(__name__)

# ======================
# CONFIG
# ======================
IDENTIFIER = os.getenv("IDENTIFIER")
PASSWORD = os.getenv("PASSWORD")

LOGIN_URL = "https://sunrise.choiceqr.com/api/auth/local"
EXPORT_URL = "https://sunrise.choiceqr.com/api/export/xlsx"

SAVE_PATH = "./exports"
EXCEL_FILE = f"{SAVE_PATH}/menu.xlsx"
PDF_FILE = f"{SAVE_PATH}/menu.pdf"

FONT_PATH = "DejaVuSans.ttf"

pdfmetrics.registerFont(TTFont("DejaVu", FONT_PATH))

# ======================
# DOWNLOAD EXCEL
# ======================
def download_excel():
    print("Downloading Excel...")

    if not IDENTIFIER or not PASSWORD:
        print("ENV variables missing")
        return

    os.makedirs(SAVE_PATH, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "accept": "*/*",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0",
        "referer": "https://sunrise.choiceqr.com/admin/"
    })

    try:
        login_payload = {
            "identifier": IDENTIFIER,
            "password": PASSWORD
        }

        login_res = session.post(LOGIN_URL, json=login_payload)

        if login_res.status_code not in (200, 201):
            print("Login error:", login_res.text)
            return

        token = login_res.json().get("token")
        if not token:
            print("Token not found")
            return

        session.headers.update({"authorization": token})

        export_res = session.get(EXPORT_URL)

        if export_res.status_code == 200:

            with open(EXCEL_FILE, "wb") as f:
                f.write(export_res.content)

            print("✔ Excel updated")

            generate_clean_menu_pdf() 

        else:
            print("Download error:", export_res.text)

    except Exception as e:
        print("Error:", e)


def split_text(text, max_len):
    if not text:
        return []

    words = str(text).split()
    lines = []
    current = ""

    for word in words:
        if len(current + " " + word) <= max_len:
            current += " " + word if current else word
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines



# ======================
# GENERATE PDF
# ======================
# ======================
# GENERATE CLEAN MENU
# ======================
def generate_clean_menu_pdf():

    if not os.path.exists(EXCEL_FILE):
        print("Excel missing")
        return

    print("Generating CLEAN MENU...")

    df = pd.read_excel(EXCEL_FILE)

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

    df = df[df["Section"].notna()]

    c = canvas.Canvas(PDF_FILE, pagesize=A4)
    width, height = A4

    MARGIN = 40
    COLUMN_GAP = 20

    usable_width = width - 2 * MARGIN
    column_width = (usable_width - COLUMN_GAP) / 2

    x_positions = [
        MARGIN,
        MARGIN + column_width + COLUMN_GAP
    ]

    column = 0
    y = height - MARGIN

    def new_page():
        nonlocal column, y
        c.showPage()
        column = 0
        y = height - MARGIN

    def new_column():
        nonlocal column, y
        column += 1
        if column > 1:
            new_page()
        else:
            y = height - MARGIN

    def ensure_space(h):
        nonlocal y
        if y - h < MARGIN:
            new_column()

    for section in SECTION_ORDER:

        section_df = df[df["Section"] == section]
        if section_df.empty:
            continue

        ensure_space(60)

        # SECTION TITLE
        c.setFont("DejaVu", 22)
        c.drawString(x_positions[column], y, section)
        y -= 30

        grouped = section_df.groupby("Category")

        for category, items in grouped:

            ensure_space(40)

            # CATEGORY
            c.setFont("DejaVu", 16)
            c.drawString(x_positions[column], y, str(category))
            y -= 20

            for _, row in items.iterrows():

                name = str(row.get("Dish name", ""))
                desc = str(row.get("Description", ""))
                price = str(row.get("Price", ""))
                weight = str(row.get("Weight, g", ""))

                name_lines = simpleSplit(name, "DejaVu", 12, column_width - 60)
                desc_lines = simpleSplit(desc, "DejaVu", 9, column_width - 20)

                block_height = (
                    len(name_lines) * 14 +
                    len(desc_lines) * 11 +
                    25
                )

                ensure_space(block_height)

                # NAME + PRICE
                c.setFont("DejaVu", 12)
                for i, line in enumerate(name_lines):
                    c.drawString(
                        x_positions[column],
                        y,
                        line
                    )
                    if i == 0:
                        c.drawRightString(
                            x_positions[column] + column_width,
                            y,
                            price
                        )
                    y -= 14

                # DESCRIPTION
                c.setFont("DejaVu", 9)
                for line in desc_lines:
                    c.drawString(
                        x_positions[column],
                        y,
                        line
                    )
                    y -= 11

                # WEIGHT
                if weight and weight != "nan":
                    c.setFont("DejaVu", 8)
                    c.drawRightString(
                        x_positions[column] + column_width,
                        y,
                        f"{weight}г"
                    )
                    y -= 12

                y -= 8

            y -= 10

        y -= 20

    c.save()
    print("✔ CLEAN MENU GENERATED")

# ======================
# SCHEDULER
# ======================
def scheduler_loop():
    schedule.every(30).minutes.do(download_excel)

    download_excel()

    while True:
        schedule.run_pending()
        time.sleep(10)


# ======================
# WEB ROUTES
# ======================
@app.route("/")
def home():
    return """
    <h1>Menu server is running</h1>
    <a href="/excel">Download Excel</a><br>
    <a href="/pdf">Download PDF</a>
    """


@app.route("/excel")
def get_excel():
    if os.path.exists(EXCEL_FILE):
        return send_file(EXCEL_FILE, as_attachment=True)

    return "Excel not ready yet"


@app.route("/pdf")
def download_pdf():
    if os.path.exists(PDF_FILE):
        return send_file(PDF_FILE, as_attachment=True)

    return "PDF not ready"


# ======================
# START SERVER
# ======================
if __name__ == "__main__":

    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
