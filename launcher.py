import sys
import os
import logging
import requests
import pymem
import pymem.process

# Определяем базовую директорию (папка, где лежит exe)
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(BASE_DIR, "debug.log")
OFFSETS_DIR = os.path.join(BASE_DIR, "offsets")

# Настройка логгера
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    encoding='utf-8'
)

logging.info(f"Запуск в директории: {BASE_DIR}")

# ================= ПАТЧИНГ REQUESTS =================
original_get = requests.get

def patched_get(url, *args, **kwargs):
    # Пытаемся найти файлы в ./offsets/
    if "offsets.json" in url:
        path = os.path.join(OFFSETS_DIR, "offsets.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                content = f.read()
            resp = requests.models.Response()
            resp._content = content.encode('utf-8')
            resp.status_code = 200
            return resp
            
    elif "client_dll.json" in url:
        path = os.path.join(OFFSETS_DIR, "client_dll.json")
        if os.path.exists(path):
            with open(path, "r") as f:
                content = f.read()
            resp = requests.models.Response()
            resp._content = content.encode('utf-8')
            resp.status_code = 200
            return resp
            
    return original_get(url, *args, **kwargs)

requests.get = patched_get

# ================= ПРОВЕРКИ =================
if not os.path.exists(OFFSETS_DIR):
    logging.error("Папка ./offsets/ не найдена!")
    sys.exit(1)

# ================= ЗАПУСК =================
try:
    logging.info("Импорт CS2ESP...")
    import CS2ESP
    logging.info("Запуск CS2ESP.main()")
    CS2ESP.main()
except Exception as e:
    logging.critical(f"Ошибка выполнения: {e}")
    sys.exit(1)
