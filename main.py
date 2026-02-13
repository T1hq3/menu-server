from flask import Flask
import requests
import schedule
import time
import threading
import os
import pandas as pd

from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, HRFlowable
)

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import mm
from flask import send_file, render_template_string


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
        login_res = session.post(LOGIN_URL, json={
            "identifier": IDENTIFIER,
            "password": PASSWORD
        })

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
            generate_menu_pdf()
        else:
            print("Download error:", export_res.text)

    except Exception as e:
        print("Error:", e)


# ======================
# CATEGORY TABLE BUILDER
# ======================

def build_category_table(category_name, items_df, frame_width, styles):

    data = []

    header_style = ParagraphStyle(
        "CatHeader",
        parent=styles["Normal"],
        fontName="DejaVu",
        fontSize=14,
        spaceBefore=6,
        spaceAfter=6,
    )

    header_para = Paragraph(f"<b>{category_name}</b>", header_style)

    data.append([header_para, ""])

    for _, row in items_df.iterrows():

        name = str(row["Dish name"]).strip()
        desc = str(row["Description"]).strip()
        price = str(row["Price"]).strip()
        weight = str(row["Weight, g"]).strip()

        if price == "0":
            price = ""

        left_html = f"<b>{name}</b>"
        if desc and desc.lower() != "nan":
            left_html += f"<br/><font size=9 color=grey>{desc}</font>"

        right_html = ""
        if price:
            right_html += f"<b>{price}</b>"
        if weight and weight.lower() != "nan":
            right_html += f"<br/><font size=8>{weight}г</font>"

        left_para = Paragraph(left_html, styles["Normal"])
        right_para = Paragraph(right_html, styles["Normal"])

        data.append([left_para, right_para])

    table = Table(
        data,
        colWidths=[frame_width * 0.75, frame_width * 0.25],
        repeatRows=1
    )

    table.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#EAEAEA")),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
    ]))

    return table


# ======================
# PDF GENERATION
# ======================

def generate_menu_pdf():

    if not os.path.exists(EXCEL_FILE):
        print("Excel missing")
        return

    print("Generating MENU PDF...")

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

    elements = []

    for section in SECTION_ORDER:

        section_df = df[df["Section"] == section]
        if section_df.empty:
            continue

        elements.append(Paragraph(section, section_style))
        elements.append(HRFlowable(width="100%", thickness=1.5))
        elements.append(Spacer(1, 14))

        for category, items in section_df.groupby("Category"):

            table = build_category_table(
                category,
                items,
                frame_width,
                styles
            )

            elements.append(table)
            elements.append(Spacer(1, 18))

        elements.append(Spacer(1, 25))

    doc.build(elements)

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
def index():

    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Menu PDF</title>
        <style>
            body {
                font-family: Arial;
                text-align: center;
                margin-top: 100px;
                background: #f5f5f5;
            }
            .btn {
                background: black;
                color: white;
                padding: 15px 30px;
                font-size: 18px;
                border-radius: 8px;
                text-decoration: none;
            }
            .btn:hover {
                background: #333;
            }
        </style>
    </head>
    <body>
        <h1>Restaurant Menu</h1>
        <a class="btn" href="/download">Download PDF</a>
    </body>
    </html>
    """

    return render_template_string(html)


@app.route("/download")
def download_pdf():

    if not os.path.exists(PDF_FILE):
        return "PDF not generated yet", 404

    return send_file(
        PDF_FILE,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=
# ======================
# START SERVER
# ======================

if __name__ == "__main__":

    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
