from flask import Flask
import requests
import schedule
import time
import threading
import os

app = Flask(__name__)

IDENTIFIER = os.getenv("IDENTIFIER")
PASSWORD = os.getenv("PASSWORD")

LOGIN_URL = "https://sunrise.choiceqr.com/api/auth/local"
EXPORT_URL = "https://sunrise.choiceqr.com/api/export/xlsx"

SAVE_PATH = "./exports"
EXCEL_FILE = f"{SAVE_PATH}/menu.xlsx"


def download_excel():
    print("Downloading Excel...")

    if not IDENTIFIER or not PASSWORD:
        print("ENV variables missing")
        return

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

        if response.status_code not in [200, 201]:
            print("Login error:", response.text)
            return

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
            print("Download error:", export_res.text)

    except Exception as e:
        print("Error:", e)


def scheduler_loop():

    schedule.every(30).minutes.do(download_excel)

    download_excel()

    while True:
        schedule.run_pending()
        time.sleep(10)


@app.route("/")
def home():
    return "Menu server is running"


if __name__ == "__main__":
    thread = threading.Thread(target=scheduler_loop)
    thread.daemon = True
    thread.start()

    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
