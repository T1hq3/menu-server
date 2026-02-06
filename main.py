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

    c = canvas.Canvas(PDF_FILE, pagesize=A4)
    width, height = A4

    # ===== PAGE / COLUMNS =====
    MARGIN_TOP = 50
    MARGIN_BOTTOM = 60
    COLUMN_GAP = 20

    column_width = (width - COLUMN_GAP) / 2 - 40
    x_positions = [30, width / 2 + 10]

    y = height - MARGIN_TOP
    column = 0
    current_section = None

    # ===== SECTION =====
    SECTION_SPACING_AFTER = 60

    # ===== CATEGORY GEOMETRY =====
    CATEGORY_HEADER_HEIGHT = 38
    CATEGORY_RADIUS = 12
    CATEGORY_PADDING_TOP = 12
    CATEGORY_PADDING_BOTTOM = 14
    CATEGORY_SPACING_AFTER = 24
    MIN_CATEGORY_BODY_HEIGHT = 40

    CONTENT_LEFT_PADDING = 12
    CONTENT_RIGHT_PADDING = 12

    # ===== HELPERS =====
    def new_page():
        nonlocal column, y
        c.showPage()
        column = 0
        y = height - MARGIN_TOP

    def new_column():
        nonlocal column, y
        column += 1
        if column > 1:
            new_page()
        y = height - MARGIN_TOP

    def ensure_space(min_height):
        nonlocal y
        if y - min_height < MARGIN_BOTTOM:
            new_column()

    def start_section():
        nonlocal y, column

        # мінімальна висота, яка потрібна section + 1 category
        MIN_SECTION_HEIGHT = SECTION_SPACING_AFTER + 120

        # якщо section не вміщається — нова сторінка
        if y - MIN_SECTION_HEIGHT < MARGIN_BOTTOM:
            c.showPage()
            column = 0
            y = height - MARGIN_TOP
            return
    
        # якщо ми не на початку колонки — переходимо в нову колонку
        if column != 0:
            new_column()




    # ===== SECTION =====
    def draw_section(title):
        nonlocal y
        c.setFont("DejaVu", 26)
        c.drawCentredString(width / 2, y, title)

        c.setLineWidth(3)
        c.line(80, y - 10, width - 80, y - 10)

        y -= SECTION_SPACING_AFTER

    # ===== CATEGORY HEADER =====
    def draw_category_header(x, title):
        nonlocal y

        c.setLineWidth(1.5)
        c.roundRect(
            x,
            y - CATEGORY_HEADER_HEIGHT,
            column_width,
            CATEGORY_HEADER_HEIGHT,
            CATEGORY_RADIUS,
            stroke=1,
            fill=0
        )

        c.setFillColorRGB(0.9, 0.9, 0.9)
        c.roundRect(
            x + 2,
            y - CATEGORY_HEADER_HEIGHT + 2,
            column_width - 4,
            CATEGORY_HEADER_HEIGHT - 4,
            CATEGORY_RADIUS - 2,
            stroke=0,
            fill=1
        )

        c.setFillColorRGB(0, 0, 0)
        c.setFont("DejaVu", 18)
        c.drawString(
            x + CONTENT_LEFT_PADDING,
            y - 26,
            title
        )

        y -= CATEGORY_HEADER_HEIGHT + CATEGORY_PADDING_TOP

    grouped = df.groupby(["Section", "Category"])

    for (section, category), items in grouped:

        # ===== SECTION =====
        if current_section != section:
            start_section()
            draw_section(str(section))
            current_section = section

        x = x_positions[column]

        ensure_space(120)
        draw_category_header(x, str(category))
        block_top = y + CATEGORY_HEADER_HEIGHT + CATEGORY_PADDING_TOP

        # ===== ITEMS =====
        for _, row in items.iterrows():

            name_lines = split_text(str(row.get("Dish name", "")), 28)
            desc_lines = split_text(str(row.get("Description", "")), 45)
            price = str(row.get("Price", ""))

            item_height = (
                len(name_lines) * 15 +
                len(desc_lines) * 13 +
                18
            )

            if y - item_height < MARGIN_BOTTOM:
                # close current category frame
                current_height = block_top - (y - CATEGORY_PADDING_BOTTOM)
                if current_height < CATEGORY_HEADER_HEIGHT + MIN_CATEGORY_BODY_HEIGHT:
                    y -= (CATEGORY_HEADER_HEIGHT + MIN_CATEGORY_BODY_HEIGHT - current_height)

                c.roundRect(
                    x,
                    y - CATEGORY_PADDING_BOTTOM,
                    column_width,
                    block_top - (y - CATEGORY_PADDING_BOTTOM),
                    CATEGORY_RADIUS
                )

                new_column()
                x = x_positions[column]
                draw_category_header(x, str(category))
                block_top = y + CATEGORY_HEADER_HEIGHT + CATEGORY_PADDING_TOP

            # --- NAME + PRICE
            c.setFont("DejaVu", 13)
            c.drawString(
                x + CONTENT_LEFT_PADDING,
                y,
                name_lines[0]
            )

            c.drawRightString(
                x + column_width - CONTENT_RIGHT_PADDING,
                y,
                price
            )

            y -= 15

            for line in name_lines[1:]:
                c.drawString(
                    x + CONTENT_LEFT_PADDING,
                    y,
                    line
                )
                y -= 15

            # --- DESCRIPTION
            c.setFont("DejaVu", 9)
            for line in desc_lines:
                c.drawString(
                    x + CONTENT_LEFT_PADDING,
                    y,
                    line
                )
                y -= 13

            y -= 8

        # ===== CLOSE CATEGORY FRAME =====
        current_height = block_top - (y - CATEGORY_PADDING_BOTTOM)
        if current_height < CATEGORY_HEADER_HEIGHT + MIN_CATEGORY_BODY_HEIGHT:
            y -= (CATEGORY_HEADER_HEIGHT + MIN_CATEGORY_BODY_HEIGHT - current_height)

        c.roundRect(
            x,
            y - CATEGORY_PADDING_BOTTOM,
            column_width,
            block_top - (y - CATEGORY_PADDING_BOTTOM),
            CATEGORY_RADIUS
        )

        y -= CATEGORY_SPACING_AFTER

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
