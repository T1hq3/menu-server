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

    print("Generating DESIGN MENU...")

    df = pd.read_excel(EXCEL_FILE)
    df = df[df["Section"].notna()]
    df = df.fillna("")

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

    c = canvas.Canvas(PDF_FILE, pagesize=A4)
    width, height = A4

    MARGIN = 40
    COLUMN_GAP = 20

    usable_width = width - 2 * MARGIN
    column_width = (usable_width - COLUMN_GAP) / 2

    x_positions = [MARGIN, MARGIN + column_width + COLUMN_GAP]

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

    def draw_section(title):
        nonlocal y
        c.setFont("DejaVu", 24)
        c.drawString(x_positions[column], y, title)
        y -= 10
        c.setLineWidth(2)
        c.line(
            x_positions[column],
            y,
            x_positions[column] + column_width,
            y
        )
        y -= 25

    for section in SECTION_ORDER:

        section_df = df[df["Section"] == section]
        if section_df.empty:
            continue

        ensure_space(80)
        draw_section(section)

        for category, items in section_df.groupby("Category"):

            header_height = 35
            block_start_y = y

            ensure_space(header_height + 20)

            x = x_positions[column]

            # HEADER BACKGROUND
            c.setFillColorRGB(0.9, 0.9, 0.9)
            c.roundRect(
                x,
                y - header_height,
                column_width,
                header_height,
                8,
                stroke=0,
                fill=1
            )

            c.setFillColorRGB(0, 0, 0)
            c.setFont("DejaVu", 16)
            c.drawString(x + 10, y - 22, str(category))

            y -= header_height + 10

            for _, row in items.iterrows():

                name = str(row["Dish name"]).strip()
                desc = str(row["Description"]).strip()
                price = str(row["Price"]).strip()
                weight = str(row["Weight, g"]).strip()

                if price == "0":
                    price = ""

                name_lines = simpleSplit(name, "DejaVu", 12, column_width - 60)
                desc_lines = simpleSplit(desc, "DejaVu", 9, column_width - 20)

                block_height = (
                    len(name_lines) * 15 +
                    len(desc_lines) * 11 +
                    20
                )

                ensure_space(block_height)

                # NAME + PRICE
                c.setFont("DejaVu", 12)

                for i, line in enumerate(name_lines):
                    c.drawString(x + 10, y, line)

                    if i == 0 and price:
                        c.setFont("DejaVu", 12)
                        c.drawRightString(
                            x + column_width - 10,
                            y,
                            price
                        )
                    y -= 15

                # dotted line
                if price:
                    c.setDash(1, 2)
                    c.line(
                        x + 10,
                        y + 12,
                        x + column_width - 10,
                        y + 12
                    )
                    c.setDash()

                # DESCRIPTION
                if desc and desc.lower() != "nan":
                    c.setFillColorRGB(0.4, 0.4, 0.4)
                    c.setFont("DejaVu", 9)

                    for line in desc_lines:
                        c.drawString(x + 10, y, line)
                        y -= 11

                    c.setFillColorRGB(0, 0, 0)

                # WEIGHT
                if weight and weight.lower() != "nan":
                    c.setFont("DejaVu", 8)
                    c.drawRightString(
                        x + column_width - 10,
                        y,
                        weight
                    )
                    y -= 12

                y -= 5

            # рамка категорії
            block_height_total = block_start_y - y
            c.roundRect(
                x,
                y,
                column_width,
                block_height_total,
                8,
                stroke=1,
                fill=0
            )

            y -= 20

    c.save()
    print("✔ DESIGN MENU GENERATED")


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
