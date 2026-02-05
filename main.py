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

            generate_pdf()  # ← автоматичне створення PDF

        else:
            print("Download error:", export_res.text)

    except Exception as e:
        print("Error:", e)


# ======================
# GENERATE PDF
# ======================
def clean_text(val):
    if pd.isna(val):
        return ""
    return str(val)


def generate_pdf():

    if not os.path.exists(EXCEL_FILE):
        print("Excel missing")
        return

    print("Generating MENU PDF...")

    df = pd.read_excel(EXCEL_FILE)
    df = df.fillna("")

    c = canvas.Canvas(PDF_FILE, pagesize=A4)

    width, height = A4

    margin = 30
    col_width = (width - margin * 3) / 2

    x_positions = [margin, margin * 2 + col_width]

    # ========= ГРУПУЄМО ПО SECTION =========
    sections = df.groupby("Section")

    for section_name, section_data in sections:

        c.setFont("DejaVu", 22)
        c.drawCentredString(width / 2, height - 40, clean_text(section_name))

        y = height - 80
        column = 0

        categories = section_data.groupby("Category")

        for category_name, items in categories:

            # перенос колонки / сторінки
            if y < 150:
                column += 1

                if column > 1:
                    c.showPage()

                    c.setFont("DejaVu", 22)
                    c.drawCentredString(width / 2, height - 40, clean_text(section_name))

                    column = 0

                y = height - 80

            x = x_positions[column]

            # ========= рамка категорії =========
            block_height = 30 + len(items) * 40

            c.roundRect(x, y - block_height, col_width, block_height, 15)

            # назва категорії
            c.setFont("DejaVu", 16)
            c.drawString(x + 10, y - 25, clean_text(category_name))

            y_item = y - 50

            for _, row in items.iterrows():

                name = clean_text(row["Dish name"])
                desc = clean_text(row["Description"])
                price = clean_text(row["Price"])
                weight = clean_text(row["Weight, g"])

                # назва
                c.setFont("DejaVu", 11)
                c.drawString(x + 10, y_item, name)

                # ціна справа
                c.drawRightString(x + col_width - 10, y_item, price)

                # крапочки
                c.setFont("DejaVu", 8)
                c.drawString(x + 160, y_item, "." * 40)

                # опис
                c.setFont("DejaVu", 8)
                c.drawString(x + 10, y_item - 12, desc)

                # грамовка
                c.drawRightString(x + col_width - 10, y_item - 12, f"{weight} г")

                y_item -= 35

            y -= block_height + 15

    c.save()

    print("✔ MENU PDF GENERATED")




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
