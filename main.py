from flask import Flask, send_file, render_template_string
import requests
import pandas as pd
import schedule
import time
import threading
import os

app = Flask(__name__)

# --- CONFIG ---
IDENTIFIER = os.getenv("IDENTIFIER")
PASSWORD = os.getenv("PASSWORD")

LOGIN_URL = "https://sunrise.choiceqr.com/api/auth/local"
EXPORT_URL = "https://sunrise.choiceqr.com/api/export/xlsx"

import os

IDENTIFIER = os.getenv("IDENTIFIER")
PASSWORD = os.getenv("PASSWORD")



# =============================
# DOWNLOAD EXCEL
# =============================
def download_excel():
    print("Downloading Excel...")

    session = requests.Session()
    payload = {"identifier": IDENTIFIER, "password": PASSWORD}

    login = session.post(LOGIN_URL, json=payload)

    if login.status_code != 200:
        print("Login failed")
        return False

    token = login.json().get("token")

    session.headers.update({"authorization": token})
    res = session.get(EXPORT_URL)

    with open(EXCEL_FILE, "wb") as f:
        f.write(res.content)

    print("Excel downloaded")
    return True


# =============================
# GENERATE PDF
# =============================
def generate_pdf():
    print("Generating PDF...")

    df = pd.read_excel(EXCEL_FILE)

    with open(PDF_FILE, "w", encoding="utf8") as f:
        for _, row in df.iterrows():
            f.write(str(row.get("Dish name", "")) + "\n")

    print("PDF created")


# =============================
# MAIN JOB
# =============================
def job():
    success = download_excel()

    if success:
        generate_pdf()


# =============================
# SCHEDULER LOOP
# =============================
def scheduler_loop():
    schedule.every(10).hours.do(job)

    # запуск одразу після старту сервера
    job()

    while True:
        schedule.run_pending()
        time.sleep(60)


# =============================
# WEB PAGE
# =============================
@app.route("/")
def home():
    return render_template_string("""
        <h1>Menu PDF Server</h1>
        <form action="/download">
            <button type="submit">Download latest PDF</button>
        </form>
    """)


# =============================
# DOWNLOAD PDF
# =============================
@app.route("/download")
def download():
    if os.path.exists(PDF_FILE):
        return send_file(PDF_FILE, as_attachment=True)

    return "PDF not ready yet"


# =============================
# START BACKGROUND THREAD
# =============================
if __name__ == "__main__":
    thread = threading.Thread(target=scheduler_loop)
    thread.daemon = True
    thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)



# =============================
# RUN SERVER
# =============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
