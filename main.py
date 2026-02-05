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

            token = response.json().get("to
