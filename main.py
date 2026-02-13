from flask import Flask, send_file, render_template_string
import requests
import schedule
import time
import threading
import os
import pandas as pd
from weasyprint import HTML

app = Flask(__name__)

IDENTIFIER = os.getenv("IDENTIFIER")
PASSWORD = os.getenv("PASSWORD")

LOGIN_URL = "https://sunrise.choiceqr.com/api/auth/local"
EXPORT_URL = "https://sunrise.choiceqr.com/api/export/xlsx"

SAVE_PATH = "./exports"
EXCEL_FILE = f"{SAVE_PATH}/menu.xlsx"
PDF_FILE = f"{SAVE_PATH}/menu.pdf"


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
# HTML BUILDER
# ======================

def build_html(df):

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

    html = """
    <html>
    <head>
    <meta charset="utf-8">
    <style>

    @page {
        size: A4;
        margin: 30px 40px;
    }

    body {
        font-family: DejaVu Sans, sans-serif;
    }

    .section {
        page-break-before: always;
    }

    .section:first-child {
        page-break-before: auto;
    }

    h1 {
        text-align: center;
        font-size: 28px;
        margin-bottom: 20px;
    }

    .columns {
        column-count: 2;
        column-gap: 40px;
    }

    .category {
        break-inside: avoid;
        margin-bottom: 25px;
    }

    .cat-header {
        background: #f2f2f2;
        padding: 8px 12px;
        border: 1px solid #bbb;
        font-weight: bold;
        margin-bottom: 10px;
    }

    .item {
        margin-bottom: 10px;
    }

    .item-top {
        display: flex;
        justify-content: space-between;
        border-bottom: 1px dotted #999;
        font-weight: bold;
    }

    .desc {
        font-size: 11px;
        color: #666;
        margin-top: 2px;
    }

    .weight {
        font-size: 10px;
        color: #888;
    }

    </style>
    </head>
    <body>
    """

    for section in SECTION_ORDER:

        section_df = df[df["Section"] == section]
        if section_df.empty:
            continue

        html += f'<div class="section">'
        html += f'<h1>{section}</h1>'
        html += '<div class="columns">'

        for category, items in section_df.groupby("Category"):

            html += f'<div class="category">'
            html += f'<div class="cat-header">{category}</div>'

            for _, row in items.iterrows():

                name = str(row.get("Dish name", "")).strip()
                desc = str(row.get("Description", "")).strip()
                price = str(row.get("Price", "")).strip()
                weight = str(row.get("Weight, g", "")).strip()

                if price == "0":
                    price = ""

                html += '<div class="item">'
                html += f'''
                    <div class="item-top">
                        <span>{name}</span>
                        <span>{price}</span>
                    </div>
                '''

                if desc:
                    html += f'<div class="desc">{desc}</div>'

                if weight and weight.lower() != "nan":
                    html += f'<div class="weight">{weight} г</div>'

                html += '</div>'

            html += '</div>'

        html += '</div></div>'

    html += "</body></html>"

    return html


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

    html = build_html(df)

    HTML(string=html).write_pdf(PDF_FILE)

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
