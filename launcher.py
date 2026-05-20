import sys
import os
import json
import requests
import pymem
import pymem.process

# ================= НАСТРОЙКИ =================
OFFSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offsets")
OFFSETS_FILE = os.path.join(OFFSETS_DIR, "offsets.json")
CLIENT_DLL_FILE = os.path.join(OFFSETS_DIR, "client_dll.json")

# ================= ПЕРЕХВАТ ЗАПРОСОВ (MONKEY PATCHING) =================
original_get = requests.get

def patched_get(url, *args, **kwargs):
    """
    Перехватывает попытки CS2ESP.py скачать офсеты из интернета
    и подменяет их локальными файлами.
    """
    if "offsets.json" in url:
        if os.path.exists(OFFSETS_FILE):
            with open(OFFSETS_FILE, "r") as f:
                content = f.read()
            resp = requests.models.Response()
            resp._content = content.encode('utf-8')
            resp.status_code = 200
            return resp
            
    elif "client_dll.json" in url:
        if os.path.exists(CLIENT_DLL_FILE):
            with open(CLIENT_DLL_FILE, "r") as f:
                content = f.read()
            resp = requests.models.Response()
            resp._content = content.encode('utf-8')
            resp.status_code = 200
            return resp
            
    return original_get(url, *args, **kwargs)

# Применяем патч ДО импорта CS2ESP
requests.get = patched_get

# ================= ПРОВЕРКА ФАЙЛОВ =================
if not os.path.exists(OFFSETS_DIR):
    print(f"[!] Ошибка: Папка {OFFSETS_DIR} не найдена. Создайте ее.")
    sys.exit(1)

if not os.path.exists(OFFSETS_FILE) or not os.path.exists(CLIENT_DLL_FILE):
    print(f"[!] Ошибка: Файлы офсетов не найдены в {OFFSETS_DIR}")
    print("Убедитесь, что там лежат: offsets.json и client_dll.json")
    sys.exit(1)

print("[+] Офсеты успешно загружены из локальной папки.")

# ================= ЗАПУСК ОСНОВНОЙ ЛОГИКИ =================
# Импортируем CS2ESP только после патчинга requests
import CS2ESP

if __name__ == '__main__':
    try:
        CS2ESP.main()
    except Exception as e:
        print(f"[!] Критическая ошибка: {e}")
        input("Нажмите Enter для выхода...")
