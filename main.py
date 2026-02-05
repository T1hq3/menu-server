from flask import Flask
import requests
import schedule
import time
import threading
import os
from datetime import datetime

app = Flask(__name__)

# --- CONFIG ---
IDENTIFIER = os.getenv("IDENTIFIER")
PASSWORD = os.getenv("PASSWORD")

LOGIN_URL = "https://sunrise.choiceqr.com/api/auth/local"
EXPORT_URL = "https://sunrise.choiceqr.com/api/export/xlsx"

SAVE_PATH = "./exports"
EXCEL_FILE = f"{SAVE_PATH}/menu.xlsx"


# ======================
# DOWNLOAD EXCEL
# ======================
def download_excel():
    print("Downloading Excel...")

    if not os.path.exists(SAVE_PATH):
        os.makedirs(SAVE_PATH)

    session = requests.Session()

    session.headers.update({
        "accept": "*/*",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0",
        "referer": "https://sunrise.choiceqr.com/admin/"
    })

    try:
        payload = {
            "identifier": IDENTIFIER,
            "password": PASSWORD
        }

        response = session.post(LOGIN_URL, json=payload)

        if response.status_code in [200, 201]:

            token = response.json().get("token")

            if not token:
                print("Token not found")
                return

            session.headers.update({"authorization": token})

            export_res = session.get(EXPORT_URL, cookies={"token": token})

            if export_res.status_code == 200:

                with open(EXCEL_FILE, "wb") as f:
                    f.write(export_res.content)

                print("✔ Excel updated")

            else:
                print("Download error:", export_res.status_code)

        else:
            print("Login error:", response.status_code)

    except Exception as e:
        print("Error:", e)


# ======================
# SCHEDULER LOOP
# ======================
def scheduler_loop():

    schedule.every(30).minutes.do(download_excel)

    # запуск одразу після старту
    download_excel()

    while True:
        schedule.run_pending()
        time.sleep(10)


# ======================
# WEB PAGE
# ======================
@app.route("/")
def home():
    return "Menu server is running"


# ======================
# START SERVER
# ======================
if __name__ == "__main__":

    thread = threading.Thread(target=scheduler_loop)
    thread.daemon = True
    thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
