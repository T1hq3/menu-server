import requests
import time
import schedule
import os
import glob
from datetime import datetime

# --- НАЛАШТУВАННЯ ---
IDENTIFIER = "Export"
PASSWORD = "123123" 

# Шлях до папки (можеш змінити на свій)
SAVE_PATH = "C:/ChoiceQR_Exports" 

# Скільки останніх файлів зберігати (щоб не забити диск)
MAX_FILES_TO_KEEP = 20 

LOGIN_URL = "https://sunrise.choiceqr.com/api/auth/local"
EXPORT_URL = "https://sunrise.choiceqr.com/api/export/xlsx"

def clean_old_files():
    """Видаляє старі файли, залишаючи лише MAX_FILES_TO_KEEP останніх"""
    files = glob.glob(os.path.join(SAVE_PATH, "*.xlsx"))
    files.sort(key=os.path.getmtime, reverse=True)
    
    if len(files) > MAX_FILES_TO_KEEP:
        for file_to_delete in files[MAX_FILES_TO_KEEP:]:
            try:
                os.remove(file_to_delete)
            except Exception as e:
                print(f"Не вдалося видалити старий файл: {e}")

def download_file():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Запуск експорту...")
    
    if not os.path.exists(SAVE_PATH):
        os.makedirs(SAVE_PATH)

    session = requests.Session()
    session.headers.update({
        "accept": "*/*",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": "https://sunrise.choiceqr.com/admin/"
    })

    try:
        # 1. Авторизація
        payload = {"identifier": IDENTIFIER, "password": PASSWORD}
        response = session.post(LOGIN_URL, json=payload)
        
        if response.status_code in [200, 201]:
            token = response.json().get('token')
            if not token:
                print("Помилка: Токен не знайдено.")
                return

            # 2. Завантаження файлу
            session.headers.update({"authorization": f"{token}"})
            export_res = session.get(EXPORT_URL, cookies={"token": token})
            
            if export_res.status_code == 200:
                # Додаємо секунди в назву, бо інакше файли будуть перезаписувати один одного
                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                filename = f"menu_{timestamp}.xlsx"
                full_file_path = os.path.join(SAVE_PATH, filename)
                
                with open(full_file_path, "wb") as f:
                    f.write(export_res.content)
                
                print(f"--- Збережено: {filename} ---")
                
                # Очищуємо папку від старих копій
                clean_old_files()
            else:
                print(f"Помилка завантаження: {export_res.status_code}")
        else:
            print(f"Помилка входу: {response.status_code}")

    except Exception as e:
        print(f"Помилка: {e}")

# НАЛАШТУВАННЯ РОЗКЛАДУ: кожні 5 секунд
schedule.every(5).seconds.do(download_file)

# Перший запуск
download_file()

print(f"\nСкрипт працює в режимі (кожні 5 сек).")
print(f"Файли тут: {os.path.abspath(SAVE_PATH)}")

while True:
    schedule.run_pending()
    time.sleep(1) # Перевірка розкладу щосекунди