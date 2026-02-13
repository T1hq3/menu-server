from flask import Flask, send_file
import requests
import schedule
import time
import threading
import os
import pandas as pd

from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate,
    Paragraph, Spacer, KeepTogether,
    Table, TableStyle
)
from reportlab.platypus.flowables import HRFlowable, Flowable

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import simpleSplit
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib import colors
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

class CategoryCard(Flowable):

    def __init__(self, title, items, width, styles):
        super().__init__()
        self.title = title
        self.items = items
        self.width = width
        self.styles = styles
        self.padding = 10
        self.header_height = 28

    def wrap(self, availWidth, availHeight):
        self.width = availWidth
        total_height = self.header_height + self.padding

        for item in self.items:
            w, h = item.wrap(self.width - 2*self.padding, availHeight)
            total_height += h + 6

        total_height += self.padding
        self.height = total_height
        return self.width, total_height

    def split(self, availWidth, availHeight):
        """
        Розбиваємо картку якщо вона не влазить.
        """

        # якщо навіть header не влазить — перенести повністю
        min_height = self.header_height + 2*self.padding
        if availHeight < min_height:
            return []

        current_height = self.header_height + self.padding
        fitting_items = []
        remaining_items = []

        for item in self.items:
            w, h = item.wrap(self.width - 2*self.padding, availHeight)

            if current_height + h + 6 <= availHeight:
                fitting_items.append(item)
                current_height += h + 6
            else:
                remaining_items.append(item)

        if not fitting_items:
            return []

        first_part = CategoryCard(
            self.title,
            fitting_items,
            self.width,
            self.styles
        )

        if remaining_items:
            second_part = CategoryCard(
                self.title,
                remaining_items,
                self.width,
                self.styles
            )
            return [first_part, second_part]

        return [first_part]

    def draw(self):
        c = self.canv
        w = self.width
        h = self.height

        c.setLineWidth(1)
        c.roundRect(0, 0, w, h, 12, stroke=1, fill=0)

        c.setFillColor(colors.HexColor("#EAEAEA"))
        c.roundRect(0, h - self.header_height, w, self.header_height, 12, stroke=0, fill=1)
        c.setFillColor(colors.black)

        c.setFont("DejaVu", 14)
        c.drawString(self.padding, h - 19, self.title)

        y = h - self.header_height - self.padding

        for item in self.items:
            iw, ih = item.wrap(w - 2*self.padding, h)
            item.drawOn(c, self.padding, y - ih)
            y -= ih + 6
            
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

    dish_style = ParagraphStyle(
        'DishStyle',
        parent=styles['Normal'],
        fontName="DejaVu",
        fontSize=12,
        leading=14
    )

    desc_style = ParagraphStyle(
        'DescStyle',
        parent=styles['Normal'],
        fontName="DejaVu",
        fontSize=9,
        textColor=colors.grey,
        leading=11
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
        elements.append(HRFlowable(width="100%", thickness=1.5))
        elements.append(Spacer(1, 14))

        for category, items in section_df.groupby("Category"):

            item_flowables = []

            for _, row in items.iterrows():

                name = str(row["Dish name"]).strip()
                desc = str(row["Description"]).strip()
                price = str(row["Price"]).strip()
                weight = str(row["Weight, g"]).strip()

                if price == "0":
                    price = ""

                # Ліва частина
                left_html = f"<b>{name}</b>"

                if desc and desc.lower() != "nan":
                    left_html += f"<br/><font size=9 color=grey>{desc}</font>"

                # Права частина
                right_html = ""

                if price:
                    right_html += f"<b>{price}</b>"

                if weight and weight.lower() != "nan":
                    right_html += f"<br/><font size=8>{weight}г</font>"

                row_table = Table(
                    [[
                        Paragraph(left_html, dish_style),
                        Paragraph(right_html, dish_style)
                    ]],
                    colWidths=[frame_width - 70, 60]
                )

                row_table.setStyle(TableStyle([
                    ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 0),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                ]))

                item_flowables.append(row_table)

            elements.append(CategoryCard(category, item_flowables, frame_width, styles))
            elements.append(Spacer(1, 20))

        elements.append(Spacer(1, 25))

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
# START SERVER
# ======================
if __name__ == "__main__":

    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
