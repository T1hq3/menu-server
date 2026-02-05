import os
import requests
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import utils
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ========= НАЛАШТУВАННЯ =========
EXCEL_FILE = "menu.xlsx"
OUTPUT_PDF = "menu.pdf"
IMAGES_FOLDER = "images"
FONT_FILE = "DejaVuSans.ttf"
# ===============================

os.makedirs(IMAGES_FOLDER, exist_ok=True)

print("Читаю Excel...")
df = pd.read_excel(EXCEL_FILE)

# Реєстрація шрифту (для кирилиці)
pdfmetrics.registerFont(TTFont("DejaVu", FONT_FILE))

# Стилі
styles = getSampleStyleSheet()

styles["BodyText"].fontName = "DejaVu"
styles["BodyText"].fontSize = 11

styles["Heading1"].fontName = "DejaVu"
styles["Heading1"].fontSize = 22

styles["Heading2"].fontName = "DejaVu"
styles["Heading2"].fontSize = 18

# Окремий стиль для назви страви
dish_title_style = ParagraphStyle(
    name="DishTitle",
    fontName="DejaVu",
    fontSize=20,
    spaceAfter=6,
    spaceBefore=6
)

elements = []

doc = SimpleDocTemplate(
    OUTPUT_PDF,
    rightMargin=40,
    leftMargin=40,
    topMargin=40,
    bottomMargin=40
)

def download_image(url, filename):
    try:
        url = str(url).strip()
        if not url.startswith("http"):
            return None

        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            with open(filename, "wb") as f:
                f.write(r.content)
            return filename
    except Exception as e:
        print("❌ Помилка зображення:", e)

    return None

def fit_image(path, max_width=240, max_height=300):
    img = utils.ImageReader(path)
    w, h = img.getSize()

    width_ratio = max_width / w
    height_ratio = max_height / h
    ratio = min(width_ratio, height_ratio)

    return Image(path, width=w * ratio, height=h * ratio)

current_section = None
current_category = None

print("Генерую PDF...")

for index, row in df.iterrows():

    section = str(row["Section"])
    category = str(row["Category"])
    name = str(row["Dish name"])
    price = str(row["Price"])
    description = str(row["Description"])
    weight = str(row["Weight, g"])
    image_url = str(row["Dish image"])

    # ===== Section =====
    if section != current_section:
        elements.append(Spacer(1, 30))
        elements.append(Paragraph(section.upper(), styles["Heading1"]))
        current_section = section
        current_category = None

    # ===== Category =====
    if category != current_category:
        elements.append(Spacer(1, 20))
        elements.append(Paragraph(category, styles["Heading2"]))
        current_category = category

    # ===== Dish title =====
    elements.append(Spacer(1, 10))
    elements.append(Paragraph(name, dish_title_style))

    # ===== Image =====
    image_url = image_url.strip()
    if image_url.startswith("http"):
        ext = image_url.split(".")[-1].split("?")[0]
        img_path = os.path.join(IMAGES_FOLDER, f"{index}.{ext}")

        saved = download_image(image_url, img_path)
        if saved:
            elements.append(Spacer(1, 6))
            elements.append(fit_image(saved))
            elements.append(Spacer(1, 8))

    # ===== Description / Weight / Price =====
    text = ""

    if description.lower() != "nan":
        text += f"{description}<br/>"

    if weight.lower() != "nan":
        text += f"{weight} g<br/>"

    text += f"<b>{price} ₴</b>"

    elements.append(Paragraph(text, styles["BodyText"]))
    elements.append(Spacer(1, 24))

doc.build(elements)

print("✅ Готово! Файл menu.pdf створено")
