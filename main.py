from flask import Flask, send_file, render_template_string
import requests
import schedule
import time
import threading
import os
import pandas as pd

from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
    NextPageTemplate, PageBreak, KeepTogether, HRFlowable
)

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib import colors


# ======================
# FLASK
# ======================

app = Flask(__name__)

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
# CATEGORY BLOCK
# ======================

def build_category_block(category_name, items_df, column_width, styles):

    elements = []

    # ----- CATEGORY HEADER -----
    header_style = ParagraphStyle(
        "CatHeader",
        parent=styles["Normal"],
        fontName="DejaVu",
        fontSize=15,
        spaceBefore=6,
        spaceAfter=6,
    )

    header_table = Table(
        [[Paragraph(f"<b>{category_name}</b>", header_style)]],
        colWidths=[column_width]
    )

    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F1F1F1")),
        ('BOX', (0,0), (-1,-1), 0.8, colors.grey),
        ('LEFTPADDING', (0,0), (-1,-1), 10),
        ('RIGHTPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
    ]))

    elements.append(header_table)
    elements.append(Spacer(1, 14))

    # ----- STYLES -----
    name_style = ParagraphStyle(
        "DishName",
        parent=styles["Normal"],
        fontName="DejaVu",
        fontSize=11,
        leading=14
    )

    desc_style = ParagraphStyle(
        "DishDesc",
        parent=styles["Normal"],
        fontName="DejaVu",
        fontSize=8,
        textColor=colors.grey,
        leading=10
    )

    for _, row in items_df.iterrows():

        name = str(row.get("Dish name", "")).strip()
        desc = str(row.get("Description", "")).strip()
        price = str(row.get("Price", "")).strip()
        weight = str(row.get("Weight, g", "")).strip()

        if price == "0":
            price = ""

        # ----- NAME + PRICE -----
        item_table = Table(
            [[
                Paragraph(f"<b>{name}</b>", name_style),
                Paragraph(f"<b>{price}</b>", name_style)
            ]],
            colWidths=[column_width * 0.75, column_width * 0.25]
        )

        item_table.setStyle(TableStyle([
            ('ALIGN', (1,0), (1,0), 'RIGHT'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
        ]))

        elements.append(item_table)

        # ----- DESCRIPTION -----
        if weight and weight.lower() != "nan":
            desc += f"   <b>{weight}г</b>"

        if desc:
            elements.append(Paragraph(desc, desc_style))

        elements.append(Spacer(1, 12))

    return KeepTogether(elements)


# ======================
# PDF GENERATION
# ======================

def generate_menu_pdf():

    if not os.path.exists(EXCEL_FILE):
        print("Excel missing")
        return

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

    PAGE_WIDTH, PAGE_HEIGHT = A4
    usable_width = PAGE_WIDTH - doc.leftMargin - doc.rightMargin
    usable_height = PAGE_HEIGHT - doc.topMargin - doc.bottomMargin

    COLUMN_GAP = 20
    column_width = (usable_width - COLUMN_GAP) / 2

    frame_full = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        usable_width,
        usable_height,
        id="full"
    )

    frame_left = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        column_width,
        usable_height,
        id="left"
    )

    frame_right = Frame(
        doc.leftMargin + column_width + COLUMN_GAP,
        doc.bottomMargin,
        column_width,
        usable_height,
        id="right"
    )

    template_full = PageTemplate(id="FullWidth", frames=[frame_full])
    template_columns = PageTemplate(id="TwoColumns", frames=[frame_left, frame_right])

    doc.addPageTemplates([template_full, template_columns])

    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = "DejaVu"

    section_style = ParagraphStyle(
        "SectionCenter",
        parent=styles["Normal"],
        fontName="DejaVu",
        fontSize=26,
        alignment=1,
        spaceAfter=10,
        spaceBefore=10
    )

    elements = []
    first_section = True

    for section in SECTION_ORDER:

        section_df = df[df["Section"] == section]
        if section_df.empty:
            continue

        if not first_section:
            elements.append(PageBreak())
        else:
            first_section = False

        elements.append(NextPageTemplate("FullWidth"))

        elements.append(Paragraph(f"<b>{section}</b>", section_style))
        elements.append(HRFlowable(width="35%", thickness=1.4))
        elements.append(Spacer(1, 40))

        elements.append(NextPageTemplate("TwoColumns"))

        for category, items in section_df.groupby("Category"):

            block = build_category_block(
                category,
                items,
                column_width,
                styles
            )

            elements.append(block)
            elements.append(Spacer(1, 24))

    doc.build(elements)

    print("✔ MENU PDF GENERATED")



# ======================
# ROUTES
# ======================

@app.route("/")
def index():
    return render_template_string("""
    <html>
    <body style="text-align:center;margin-top:100px;">
        <h1>Restaurant Menu</h1>
        <a href="/download">Download PDF</a>
    </body>
    </html>
    """)

@app.route("/download")
def download_pdf():

    if not os.path.exists(PDF_FILE):
        return "PDF not generated yet", 404

    return send_file(
        PDF_FILE,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="menu.pdf"
    )


# ======================
# START
# ======================

if __name__ == "__main__":

    t = threading.Thread(target=download_excel, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
