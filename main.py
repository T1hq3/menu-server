from flask import Flask, send_file
import requests
import schedule
import time
import threading
import os
from reportlab.platypus import Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
import pandas as pd
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, KeepTogether
)
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib import colors
from reportlab.platypus.flowables import HRFlowable
from reportlab.platypus import Flowable
from reportlab.lib.units import mm

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
from reportlab.platypus import Table, TableStyle


def generate_clean_menu_pdf():

    if not os.path.exists(EXCEL_FILE):
        print("Excel missing")
        return

    print("Generating FINAL DESIGN MENU...")

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

    doc = BaseDocTemplate(
        PDF_FILE,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=40,
        bottomMargin=40
    )

    frame_width = (A4[0] - 80 - 20) / 2
    frame_height = A4[1] - 80

    frames = [
        Frame(30, 40, frame_width, frame_height, id='col1'),
        Frame(30 + frame_width + 20, 40, frame_width, frame_height, id='col2')
    ]

    doc.addPageTemplates(PageTemplate(id='TwoCol', frames=frames))

    styles = getSampleStyleSheet()

    section_style = ParagraphStyle(
        'SectionStyle',
        parent=styles['Heading1'],
        fontName="DejaVu",
        fontSize=22,
        spaceAfter=6,
    )

    category_style = ParagraphStyle(
        'CategoryStyle',
        parent=styles['Normal'],
        fontName="DejaVu",
        fontSize=15,
        textColor=colors.black,
        spaceBefore=4,
        spaceAfter=6
    )

    dish_style = ParagraphStyle(
        'DishStyle',
        parent=styles['Normal'],
        fontName="DejaVu",
        fontSize=12,
    )

    desc_style = ParagraphStyle(
        'DescStyle',
        parent=styles['Normal'],
        fontName="DejaVu",
        fontSize=9,
        textColor=colors.grey,
    )

    weight_style = ParagraphStyle(
        'WeightStyle',
        parent=styles['Normal'],
        fontName="DejaVu",
        fontSize=8,
        alignment=2
    )

    elements = []

    for section in SECTION_ORDER:

        section_df = df[df["Section"] == section]
        if section_df.empty:
            continue

        elements.append(Paragraph(section, section_style))
        elements.append(HRFlowable(width="100%", thickness=1))
        elements.append(Spacer(1, 10))

        for category, items in section_df.groupby("Category"):

            # CATEGORY HEADER TABLE (фон + рамка)
            cat_table = Table(
                [[Paragraph(f"<b>{category}</b>", category_style)]],
                colWidths=[frame_width]
            )

            cat_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#EAEAEA")),
                ('BOX', (0, 0), (-1, -1), 1, colors.black),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 6),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ]))

            elements.append(cat_table)
            elements.append(Spacer(1, 6))

            for _, row in items.iterrows():

                name = row["Dish name"]
                desc = row["Description"]
                price = str(row["Price"])
                weight = str(row["Weight, g"])

                if price == "0":
                    price = ""

                # NAME + PRICE як 2 колонки
                row_table = Table(
                    [[
                        Paragraph(name, dish_style),
                        Paragraph(f"<b>{price}</b>", dish_style)
                    ]],
                    colWidths=[frame_width - 60, 60]
                )

                row_table.setStyle(TableStyle([
                    ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ]))

                elements.append(row_table)

                if desc and desc.lower() != "nan":
                    elements.append(Paragraph(desc, desc_style))

                if weight and weight.lower() != "nan":
                    elements.append(Paragraph(f"{weight}г", weight_style))

                elements.append(Spacer(1, 8))

            elements.append(Spacer(1, 14))

        elements.append(Spacer(1, 20))

    doc.build(elements)

    print("✔ FINAL DESIGN MENU GENERATED")
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
