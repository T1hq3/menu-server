from flask import Flask, send_file, render_template_string, jsonify
import requests
import time
import threading
import os
import html
import pandas as pd
from weasyprint import HTML
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import logging

# ======================
# CONFIG
# ======================

app = Flask(__name__)

SAVE_PATH = "./exports"

VENUES = {
    "sunrise": {
        "name": "Sunrise",
        "subbrand": "Офіційне меню ресторану Sunrise",
        "identifier_env": "SUNRISE_IDENTIFIER",
        "password_env": "SUNRISE_PASSWORD",
        "identifier": os.getenv("SUNRISE_IDENTIFIER") or os.getenv("IDENTIFIER"),
        "password": os.getenv("SUNRISE_PASSWORD") or os.getenv("PASSWORD"),
        "login_url": "https://sunrise.choiceqr.com/api/auth/local",
        "export_url": "https://sunrise.choiceqr.com/api/export/xlsx",
        "referer": "https://sunrise.choiceqr.com/admin/",
        "section_order": [
            "Сети", "Роли", "Кухня", "Ланчі 11:00-17:00",
            "Коктейльна карта", "Гарячі напої",
            "Безалкогольний бар", "Алкогольний бар", "Винна карта",
        ],
        "excluded_sections": [],
    },
    "babuin": {
        "name": "BABUIN",
        "subbrand": "Офіційне меню ресторану BABUIN",
        "identifier_env": "BABUIN_IDENTIFIER",
        "password_env": "BABUIN_PASSWORD",
        "identifier": os.getenv("BABUIN_IDENTIFIER"),
        "password": os.getenv("BABUIN_PASSWORD"),
        "login_url": "https://babuin.choiceqr.com/api/auth/local",
        "export_url": "https://babuin.choiceqr.com/api/export/xlsx",
        "referer": "https://babuin.choiceqr.com/admin/",
        "section_order": [
            "BBQ Меню",
            "Основне Меню",
            "Ланчі та бранчі з 12:00 до 17:00",
            "Коктейльна карта",
            "Гарячі напої",
            "Безалкогольний бар",
            "Пиво",
            "Винна карта",
            "Алкогольний бар",
        ],
        "excluded_sections": ["Банкетне меню", "Кейтеринг", "Кайтеринг", "Кейтеринг BABUIN"],
    },
    "hochu-z-yisti": {
        "name": "hochu-z-yisti",
        "subbrand": "Офіційне меню закладу hochu-z-yisti",
        "identifier_env": "HOCHU_Z_YISTI_IDENTIFIER",
        "password_env": "HOCHU_Z_YISTI_PASSWORD",
        "identifier": os.getenv("HOCHU_Z_YISTI_IDENTIFIER") or os.getenv("IDENTIFIER"),
        "password": os.getenv("HOCHU_Z_YISTI_PASSWORD") or os.getenv("PASSWORD"),
        "login_url": "https://hochu-z-yisti.choiceqr.com/api/auth/local",
        "export_url": "https://hochu-z-yisti.choiceqr.com/api/export/xlsx",
        "referer": "https://hochu-z-yisti.choiceqr.com/admin/",
        "section_order": [],
        "excluded_sections": [],
    },
    "hochu-rebra": {
        "name": "hochu-rebra",
        "subbrand": "Офіційне меню закладу hochu-rebra",
        "identifier_env": "HOCHU_REBRA_IDENTIFIER",
        "password_env": "HOCHU_REBRA_PASSWORD",
        "identifier": os.getenv("HOCHU_REBRA_IDENTIFIER") or os.getenv("IDENTIFIER"),
        "password": os.getenv("HOCHU_REBRA_PASSWORD") or os.getenv("PASSWORD"),
        "login_url": "https://hochu-rebra.choiceqr.com/api/auth/local",
        "export_url": "https://hochu-rebra.choiceqr.com/api/export/xlsx",
        "referer": "https://hochu-rebra.choiceqr.com/admin/",
        "section_order": [],
        "excluded_sections": [],
    },
    "yo-yo": {
        "name": "yo-yo",
        "subbrand": "Офіційне меню закладу yo-yo",
        "identifier_env": "YO_YO_IDENTIFIER",
        "password_env": "YO_YO_PASSWORD",
        "identifier": os.getenv("YO_YO_IDENTIFIER") or os.getenv("IDENTIFIER"),
        "password": os.getenv("YO_YO_PASSWORD") or os.getenv("PASSWORD"),
        "login_url": "https://yo-yo.choiceqr.com/api/auth/local",
        "export_url": "https://yo-yo.choiceqr.com/api/export/xlsx",
        "referer": "https://yo-yo.choiceqr.com/admin/",
        "section_order": [],
        "excluded_sections": [],
    },
}

UPDATE_INTERVAL = 7200  # 2 hours
KYIV_TIMEZONE = ZoneInfo("Europe/Kyiv")


def now_kyiv():
    return datetime.now(KYIV_TIMEZONE)

update_lock = threading.Lock()

STATUS = {
    "last_update": None,
    "next_update": None,
    "countdown": 0,
    "venues": {
        key: {
            "excel_downloaded": False,
            "pdf_generated": False,
            "pdf_ready": False,
            "last_success": None,
            "last_attempt": None,
            "error": None,
        }
        for key in VENUES
    }
}


# ======================
# LOGGING
# ======================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)


def venue_paths(venue_key):
    venue_dir = os.path.join(SAVE_PATH, venue_key)
    return {
        "dir": venue_dir,
        "excel": os.path.join(venue_dir, "menu.xlsx"),
        "pdf": os.path.join(venue_dir, "menu.pdf"),
    }


def refresh_pdf_ready_flags():
    for venue_key in VENUES:
        paths = venue_paths(venue_key)
        STATUS["venues"][venue_key]["pdf_ready"] = os.path.exists(paths["pdf"]) and os.path.getsize(paths["pdf"]) > 0


# ======================
# LOGIN
# ======================

def login_and_get_session(venue_key):
    venue = VENUES[venue_key]

    missing_envs = []
    if not venue["identifier"]:
        missing_envs.append(venue["identifier_env"])
    if not venue["password"]:
        missing_envs.append(venue["password_env"])

    if missing_envs:
        missing_envs_str = ", ".join(missing_envs)
        raise Exception(f"Missing required ENV variables: {missing_envs_str}")

    session = requests.Session()

    session.headers.update({
        "accept": "*/*",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": venue["referer"],
    })

    logging.info(f"[{venue_key}] Sending login request...")

    response = session.post(
        venue["login_url"],
        json={
            "identifier": venue["identifier"],
            "password": venue["password"],
        },
        timeout=15
    )

    logging.info(f"[{venue_key}] Login status: {response.status_code}")

    if response.status_code not in (200, 201):
        raise Exception(f"Login failed: {response.status_code} | {response.text}")

    try:
        data = response.json()
        token = data.get("token")
    except Exception:
        raise Exception("Invalid login response")

    if not token:
        raise Exception("Token not received")

    session.headers.update({"authorization": token})
    session.cookies.set("token", token)

    logging.info(f"[{venue_key}] Login successful")

    return session


# ======================
# DOWNLOAD EXCEL
# ======================

def download_excel(session, venue_key):
    paths = venue_paths(venue_key)
    venue = VENUES[venue_key]

    if os.path.exists(paths["excel"]):
        os.remove(paths["excel"])

    response = session.get(venue["export_url"], timeout=30)

    if response.status_code != 200:
        raise Exception(f"Excel download failed: {response.status_code}")

    with open(paths["excel"], "wb") as f:
        f.write(response.content)

    if not os.path.exists(paths["excel"]) or os.path.getsize(paths["excel"]) == 0:
        raise Exception("Excel file corrupted")

    STATUS["venues"][venue_key]["excel_downloaded"] = True
    logging.info(f"[{venue_key}] ✔ Excel downloaded")


# ======================
# HTML BUILDER
# ======================

def build_html(df, venue_key):
    venue = VENUES[venue_key]
    section_order = venue.get("section_order", [])
    excluded_sections = set(venue.get("excluded_sections", []))

    def normalize_section(section_name):
        return " ".join(str(section_name).split()).strip().lower()

    normalized_section_map = {
        normalize_section(section): section
        for section in df["Section"].dropna().unique().tolist()
    }

    if excluded_sections:
        excluded_normalized = {normalize_section(section) for section in excluded_sections}
        df = df[~df["Section"].map(normalize_section).isin(excluded_normalized)]

    section_order = [
        normalized_section_map.get(normalize_section(section), section)
        for section in section_order
    ]

    def render_item(row):
        name = html.escape(str(row.get("Dish name", "")).strip())
        desc = html.escape(str(row.get("Description", "")).strip())
        price = html.escape(str(row.get("Price", "")).strip())
        weight = str(row.get("Weight, g", "")).strip()

        if price == "0":
            price = ""

        desc_html = f'<div class="item-desc">{desc}</div>' if desc else ""
        weight_html = ""

        if weight and weight.lower() != "nan":
            weight_html = f'<div class="item-weight">{html.escape(weight)} г</div>'

        details_html = ""
        if desc_html or weight_html:
            details_html = f'''
            <div class="item-details">
                {desc_html}
                {weight_html}
            </div>
            '''

        price_html = ""
        if price:
            price_html = f'<span class="dots" aria-hidden="true"></span><span class="price">{price}</span>'

        return f"""
        <div class="item">
            <div class="item-top">
                <span class="dish-name">{name}</span>
                {price_html}
            </div>
            {details_html}
        </div>
        """

    def render_category(category, items):
        safe_category = html.escape(str(category).strip())
        block = f"""
        <table class="category-card">
            <thead>
                <tr>
                    <th class="cat-header">{safe_category}</th>
                </tr>
            </thead>
            <tbody>
        """

        for _, row in items.iterrows():
            block += f"""
            <tr>
                <td>{render_item(row)}</td>
            </tr>
            """

        block += """
            </tbody>
        </table>
        """

        return block

    html_content = f"""
    <html>
    <head>
    <meta charset="utf-8">
    <style>
    @page {{
        size: A4;
        margin: 8mm 8mm;

        @bottom-center {{
            content: counter(page);
            font-size: 9px;
            color: #777;
        }}
    }}

    body {{
        font-family: "DejaVu Sans", sans-serif;
        color: #111;
        margin: 0;
        font-size: 11px;
    }}

    .cover-page {{
        page-break-after: always;
        min-height: calc(297mm - 16mm);
        display: flex;
        align-items: center;
        justify-content: center;
    }}

    .cover-card {{
        width: 100%;
        border: 1px solid #111;
        border-radius: 10px;
        text-align: center;
        padding: 14px 10px;
        background: linear-gradient(180deg, #ffffff 0%, #f1f1f1 100%);
    }}

    .menu-brand {{
        font-size: 46px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 2px;
        line-height: 1;
        margin-bottom: 10px;
    }}

    .menu-subbrand {{
        font-size: 14px;
        font-weight: 700;
        color: #444;
        text-transform: uppercase;
        letter-spacing: 1px;
    }}

    .section-page {{
        page-break-before: always;
    }}

    .section-page:first-of-type {{
        page-break-before: auto;
    }}

    .section-title {{
        font-size: 18px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 1px;
        text-align: center;
        margin: 0 0 8px 0;
        border: 1px solid #555;
        border-radius: 6px;
        padding: 4px 8px;
        background: #ececec;
    }}

    .menu-columns {{
        column-count: 2;
        column-gap: 6mm;
    }}

    .category-card {{
        width: 100%;
        border-collapse: separate;
        border-spacing: 0;
        border: 1px solid #8f8f8f;
        border-radius: 5px;
        padding: 4px 5px;
        margin: 0 0 4px 0;
        break-inside: auto;
        page-break-inside: auto;
        box-decoration-break: clone;
        -webkit-box-decoration-break: clone;
        background: #fff;
    }}

    .category-card thead {{
        display: table-header-group;
    }}

    .cat-header {{
        text-align: left;
        font-size: 12px;
        font-weight: 900;
        text-transform: uppercase;
        letter-spacing: 0.4px;
        padding: 2px 4px;
        background: #f5f5f5;
        border-radius: 3px;
    }}

    .category-card td {{
        padding: 0;
    }}

    .item {{
        margin-bottom: 4px;
        break-inside: avoid;
    }}

    .item-desc {{
        font-size: 8.8px;
        color: #555;
        line-height: 1.15;
        margin-top: 1px;
        flex: 1 1 auto;
        min-width: 0;
    }}

    .item-details {{
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        gap: 8px;
    }}

    .item-weight {{
        font-size: 9px;
        color: #666;
        margin-top: 1px;
        line-height: 1.15;
        text-align: right;
        white-space: nowrap;
        flex: 0 0 auto;
    }}

    .item:last-child {{
        margin-bottom: 1px;
    }}

    .item-top {{
        display: flex;
        align-items: baseline;
        gap: 6px;
    }}

    .dots {{
        flex: 1 1 auto;
        border-bottom: 1px dotted #666;
        transform: translateY(-2px);
        min-width: 10px;
    }}

    .dish-name {{
        font-size: 12px;
        font-weight: 700;
        line-height: 1.15;
    }}

    .price {{
        font-size: 11.6px;
        font-weight: 700;
        white-space: nowrap;
    }}

    .item-top:last-child {{
        border-bottom: none;
    }}

    .menu-columns,
    .item {{
        orphans: 2;
        widows: 2;
    }}

    .menu-columns {{
        column-fill: auto;
        min-height: 0;
    }}

    </style>
    </head>
    <body>
        <section class="cover-page">
            <div class="cover-card">
                <div class="menu-brand">{html.escape(venue['name'])} Menu</div>
                <div class="menu-subbrand">{html.escape(venue['subbrand'])}</div>
            </div>
        </section>
    """

    ordered_df = []

    for section in section_order:
        section_df = df[df["Section"] == section]
        if not section_df.empty:
            ordered_df.append((section, section_df))

    remaining_sections = [s for s in df["Section"].dropna().unique().tolist() if s not in section_order]
    for section in remaining_sections:
        section_df = df[df["Section"] == section]
        if not section_df.empty:
            ordered_df.append((section, section_df))

    for section, section_df in ordered_df:
        safe_section = html.escape(str(section).strip())
        html_content += f"""
        <section class="section-page">
            <div class="section-title">{safe_section}</div>
            <div class="menu-columns">
        """

        for category, items in section_df.groupby("Category", sort=False):
            html_content += render_category(category, items)

        html_content += """
            </div>
        </section>
        """

    html_content += """
    </body>
    </html>
    """

    return html_content


# ======================
# GENERATE PDF
# ======================

def generate_menu_pdf(venue_key):
    paths = venue_paths(venue_key)

    if not os.path.exists(paths["excel"]):
        raise Exception("Excel missing")

    df = pd.read_excel(paths["excel"])
    required_columns = ["Section", "Category", "Dish name", "Description", "Price", "Weight, g"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise Exception(f"Excel missing required columns: {', '.join(missing_columns)}")

    df = df[df["Section"].notna()]
    df = df.fillna("")

    html_content = build_html(df, venue_key)

    if os.path.exists(paths["pdf"]):
        os.remove(paths["pdf"])

    try:
        HTML(string=html_content).write_pdf(paths["pdf"])
    except Exception as e:
        raise Exception(f"PDF generation error: {str(e)}")

    if not os.path.exists(paths["pdf"]) or os.path.getsize(paths["pdf"]) == 0:
        raise Exception("PDF generation failed")

    STATUS["venues"][venue_key]["pdf_generated"] = True
    STATUS["venues"][venue_key]["pdf_ready"] = True
    logging.info(f"[{venue_key}] ✔ PDF generated")


# ======================
# UPDATE MENU
# ======================

def update_venue_menu(venue_key):
    venue_status = STATUS["venues"][venue_key]
    previous_pdf_ready = venue_status.get("pdf_ready", False)

    venue_status.update({
        "error": None,
        "excel_downloaded": False,
        "pdf_generated": False,
        "pdf_ready": previous_pdf_ready,
        "last_attempt": now_kyiv(),
    })

    paths = venue_paths(venue_key)
    os.makedirs(paths["dir"], exist_ok=True)

    with login_and_get_session(venue_key) as session:
        download_excel(session, venue_key)

    generate_menu_pdf(venue_key)
    venue_status["last_success"] = now_kyiv()


def update_menu():
    if not update_lock.acquire(blocking=False):
        logging.warning("Update already running")
        return

    logging.info("=== START UPDATE ===")

    try:
        os.makedirs(SAVE_PATH, exist_ok=True)

        for venue_key in VENUES:
            try:
                update_venue_menu(venue_key)
            except Exception as e:
                STATUS["venues"][venue_key]["error"] = str(e)
                logging.exception(f"[{venue_key}] Update failed")

        STATUS["last_update"] = now_kyiv()
        STATUS["next_update"] = now_kyiv() + timedelta(seconds=UPDATE_INTERVAL)

        logging.info("=== UPDATE COMPLETE ===")

    finally:
        update_lock.release()


# ======================
# ROUTES
# ======================

@app.route("/")
def index():
    venue_cards = [
        {
            "key": venue_key,
            "name": VENUES[venue_key]["name"],
        }
        for venue_key in VENUES
    ]

    return render_template_string("""
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {
                margin: 0;
                padding: 36px 18px;
                background: radial-gradient(circle at top, #f9fafb 0%, #eef2ff 45%, #e2e8f0 100%);
                font-family: Arial, sans-serif;
                color: #171717;
            }

            .layout {
                max-width: 980px;
                margin: 0 auto;
            }

            .hero {
                background: linear-gradient(145deg, #ffffff, #f8fafc);
                border: 1px solid #dbe2ea;
                border-radius: 18px;
                box-shadow: 0 10px 30px rgba(15, 23, 42, 0.08);
                padding: 28px 24px;
                text-align: center;
                margin-bottom: 20px;
            }

            h1 {
                margin: 0;
            }

            .subtitle {
                font-size: 13px;
                color: #666;
                margin-top: 4px;
                margin-bottom: 10px;
                text-transform: uppercase;
                letter-spacing: 0.7px;
            }

            .intro {
                margin: 0;
                color: #444;
                font-size: 14px;
            }

            .venues-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
                gap: 14px;
                margin-bottom: 20px;
            }

            .venue-card {
                background: #ffffffd1;
                backdrop-filter: blur(2px);
                border: 1px solid #d9e0ea;
                border-radius: 14px;
                padding: 14px;
                box-shadow: 0 8px 18px rgba(15, 23, 42, 0.06);
            }

            .venue-title {
                margin: 0 0 10px 0;
                font-size: 18px;
            }

            .download-btn {
                border: none;
                background: linear-gradient(145deg, #111827, #1f2937);
                color: #fff;
                font-size: 14px;
                border-radius: 10px;
                padding: 10px 12px;
                cursor: pointer;
                font-weight: 700;
                width: 100%;
            }

            .download-btn:hover {
                background: linear-gradient(145deg, #1f2937, #374151);
            }

            .download-btn:disabled {
                opacity: 0.7;
                cursor: wait;
            }

            .status-row {
                margin-top: 10px;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .status-light {
                width: 12px;
                height: 12px;
                border-radius: 999px;
                border: 1px solid #a8a8a8;
                background: #9ca3af;
                box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.17);
            }

            .status-ok {
                background: #16a34a;
                box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.18);
                border-color: #15803d;
            }

            .status-busy {
                background: #f59e0b;
                box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.2);
                border-color: #b45309;
            }

            .status-error {
                background: #dc2626;
                box-shadow: 0 0 0 3px rgba(248, 113, 113, 0.2);
                border-color: #b91c1c;
            }

            .status-label {
                font-size: 12px;
                font-weight: 700;
                color: #334155;
            }

            .ready-badge,
            .pending-badge,
            .error-badge {
                margin-top: 10px;
                font-size: 12px;
                font-weight: 700;
            }

            .ready-badge { color: #0a6e35; }

            .pending-badge { color: #8a6c00; }

            .error-badge { color: #b91c1c; }

            .guide {
                background: #fff;
                border: 1px solid #d4d4d4;
                border-radius: 16px;
                box-shadow: 0 8px 25px rgba(0, 0, 0, 0.07);
                padding: 20px 24px;
            }

            .guide h2 {
                margin-top: 0;
                margin-bottom: 8px;
                font-size: 20px;
            }

            .guide ol {
                margin: 10px 0 0 18px;
                padding: 0;
                color: #333;
                font-size: 14px;
                line-height: 1.45;
            }

            .countdown {
                margin-top: 12px;
                font-size: 13px;
                color: #555;
                font-weight: 600;
            }
        </style>
    </head>
    <body>
        <div class="layout">
            <section class="hero">
                <h1>ChoiceQR Menu Export</h1>
                <div class="subtitle">Офіційні PDF меню закладів</div>
                <p class="intro">Кожен заклад винесений в окрему картку для швидкого завантаження потрібного меню.</p>
                <div id="excel-countdown" class="countdown">До наступного завантаження Excel: оновлення виконується</div>
            </section>

            <section class="venues-grid">
                {% for venue in venue_cards %}
                <article class="venue-card" data-venue="{{ venue.key }}">
                    <h3 class="venue-title">{{ venue.name }}</h3>
                    <button type="button" class="download-btn" data-download="{{ venue.key }}">Завантажити PDF меню</button>
                    <div class="status-row">
                        <span class="status-light" data-light="{{ venue.key }}"></span>
                        <span class="status-label" data-label="{{ venue.key }}">Перевіряємо статус...</span>
                    </div>
                    <div class="pending-badge" data-message="{{ venue.key }}">Оновлення статусу...</div>
                </article>
                {% endfor %}
            </section>

            <section class="guide">
                <h2>Інструкція користування сайтом</h2>
                <ol>
                    <li>Оберіть картку потрібного закладу.</li>
                    <li>Натисніть кнопку <b>«Завантажити PDF меню»</b>.</li>
                    <li>Відкрийте завантажений файл або одразу передайте його гостю.</li>
                    <li>Якщо меню ще оновлюється, зачекайте до завершення таймера і повторіть спробу.</li>
                </ol>
            </section>
        </div>

        <script>
            let countdownSeconds = 0;

            function formatCountdown(seconds) {
                if (!seconds || seconds <= 0) {
                    return "оновлення виконується";
                }

                const hours = Math.floor(seconds / 3600);
                const minutes = Math.floor((seconds % 3600) / 60);
                const secs = seconds % 60;
                return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
            }

            function updateCountdownText() {
                const node = document.getElementById("excel-countdown");
                if (!node) {
                    return;
                }

                node.textContent = `До наступного завантаження Excel: ${formatCountdown(countdownSeconds)}`;
            }

            function applyVenueStatus(venueKey, venueStatus, override = null) {
                const light = document.querySelector(`[data-light='${venueKey}']`);
                const label = document.querySelector(`[data-label='${venueKey}']`);
                const message = document.querySelector(`[data-message='${venueKey}']`);
                if (!light || !label || !message) {
                    return;
                }

                light.className = "status-light";

                if (override === "downloading") {
                    light.classList.add("status-busy");
                    label.textContent = "Йде завантаження файлу";
                    message.className = "pending-badge";
                    message.textContent = "Завантаження PDF...";
                    return;
                }

                if (venueStatus.error) {
                    light.classList.add("status-error");
                    label.textContent = "Помилка";
                    message.className = "error-badge";
                    message.textContent = venueStatus.error;
                    return;
                }

                if (venueStatus.pdf_ready) {
                    light.classList.add("status-ok");
                    label.textContent = "Все добре";
                    message.className = "ready-badge";
                    message.textContent = "PDF готовий до завантаження";
                    return;
                }

                light.classList.add("status-busy");
                label.textContent = "Оновлення";
                message.className = "pending-badge";
                message.textContent = "Меню оновлюється, спробуйте трохи пізніше";
            }

            async function refreshStatus() {
                try {
                    const response = await fetch("/status", { cache: "no-store" });
                    if (!response.ok) return;

                    const payload = await response.json();
                    countdownSeconds = Number(payload.countdown_seconds || 0);
                    updateCountdownText();

                    Object.entries(payload.venues || {}).forEach(([venueKey, venueStatus]) => {
                        applyVenueStatus(venueKey, venueStatus);
                    });
                } catch (e) {
                    // ignore temporary network errors
                }
            }

            async function handleDownload(event) {
                const button = event.currentTarget;
                const venueKey = button.getAttribute("data-download");

                button.disabled = true;
                applyVenueStatus(venueKey, {}, "downloading");

                try {
                    const response = await fetch(`/download/${venueKey}`);
                    if (!response.ok) {
                        const errorText = await response.text();
                        throw new Error(errorText || "download failed");
                    }

                    const blob = await response.blob();
                    const url = URL.createObjectURL(blob);
                    const anchor = document.createElement("a");
                    anchor.href = url;
                    anchor.download = `menu-${venueKey}.pdf`;
                    document.body.appendChild(anchor);
                    anchor.click();
                    anchor.remove();
                    URL.revokeObjectURL(url);
                } catch (e) {
                    applyVenueStatus(venueKey, { error: `Не вдалося завантажити PDF: ${e.message}` });
                } finally {
                    button.disabled = false;
                    refreshStatus();
                }
            }

            document.querySelectorAll("[data-download]").forEach((button) => {
                button.addEventListener("click", handleDownload);
            });

            setInterval(() => {
                if (countdownSeconds > 0) {
                    countdownSeconds -= 1;
                }
                updateCountdownText();
            }, 1000);

            setInterval(refreshStatus, 10000);
            refreshStatus();
        </script>
    </body>
    </html>
    """, venue_cards=venue_cards)


@app.route("/download/<venue_key>")
def download_pdf(venue_key):
    refresh_pdf_ready_flags()

    if venue_key not in VENUES:
        return "Unknown venue", 404

    if not STATUS["venues"][venue_key]["pdf_ready"]:
        return "PDF not ready yet", 503

    paths = venue_paths(venue_key)
    if not os.path.exists(paths["pdf"]):
        STATUS["venues"][venue_key]["pdf_ready"] = False
        return "PDF not ready yet", 503

    return send_file(
        paths["pdf"],
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"menu-{venue_key}.pdf"
    )


@app.route("/status")
def status():
    refresh_pdf_ready_flags()

    venues_payload = {}
    for venue_key, venue_status in STATUS["venues"].items():
        venues_payload[venue_key] = {
            **venue_status,
            "last_success": venue_status["last_success"].isoformat() if venue_status["last_success"] else None,
            "last_attempt": venue_status["last_attempt"].isoformat() if venue_status["last_attempt"] else None,
        }

    return jsonify({
        "timezone": "Europe/Kyiv",
        "last_update": STATUS["last_update"].isoformat() if STATUS["last_update"] else None,
        "next_update": STATUS["next_update"].isoformat() if STATUS["next_update"] else None,
        "countdown_seconds": STATUS["countdown"],
        "venues": venues_payload,
    })


# ======================
# BACKGROUND WORKER
# ======================

def background_worker():
    refresh_pdf_ready_flags()
    update_menu()  # first run immediately

    while True:
        for i in range(UPDATE_INTERVAL, 0, -1):
            STATUS["countdown"] = i
            time.sleep(1)

        update_menu()


# ======================
# START
# ======================

if __name__ == "__main__":
    t = threading.Thread(target=background_worker, daemon=True)
    t.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
