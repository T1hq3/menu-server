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


# ======================
# GENERATE PDF
# ======================
def generate_clean_menu_pdf():

    if not os.path.exists(EXCEL_FILE):
        print("Excel missing")
        return

    print("Generating CLEAN MENU...")

    df = pd.read_excel(EXCEL_FILE)

    c = canvas.Canvas(PDF_FILE, pagesize=A4)

    width, height = A4

    column_width = width / 2 - 40
    x_positions = [30, width / 2 + 10]

    y = height - 40
    column = 0
    current_section = None


    def new_page():
        nonlocal column, y
        c.showPage()
        column = 0
        y = height - 40


    def new_column():
        nonlocal column, y

        column += 1
        if column > 1:
            new_page()

        y = height - 40


    grouped = df.groupby(["Section", "Category"])


    for (section, category), items in grouped:

        # ---------- SECTION ----------
        if current_section != section:

            if y < 120:
                new_column()

            c.setFont("DejaVu", 22)
            c.drawCentredString(width / 2, y, str(section))
            y -= 35

            current_section = section


        x = x_positions[column]

        # ---------- CATEGORY HEADER ----------
        def draw_category_header():

            c.setFillColorRGB(0.85, 0.85, 0.85)
            c.rect(x, y - 35, column_width, 35, fill=1, stroke=0)

            c.setFillColorRGB(0, 0, 0)
            c.setFont("DejaVu", 18)
            c.drawString(x + 10, y - 25, str(category))


        # Малюємо header
        draw_category_header()

        item_y = y - 50


        for _, row in items.iterrows():

            name_lines = split_text(row.get("Dish name", ""), 28)
            desc_lines = split_text(row.get("Description", ""), 45)

            item_height = (
                len(name_lines) * 15 +
                len(desc_lines) * 12 +
                15
            )


            # ----- перенос item -----
            if item_y - item_height < 60:

                new_column()
                x = x_positions[column]

                draw_category_header()
                item_y = y - 50


            price = str(row.get("Price", ""))


            # ----- NAME -----
            c.setFont("DejaVu", 13)

            for line in name_lines:
                c.drawString(x + 10, item_y, line)
                item_y -= 15


            # ----- PRICE -----
            c.drawRightString(
                x + column_width - 10,
                item_y + 15,
                price
            )


            # ----- DESCRIPTION -----
            c.setFont("DejaVu", 9)

            for line in desc_lines:
                c.drawString(x + 10, item_y, line)
                item_y -= 12

            item_y -= 6


        y = item_y - 25


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
