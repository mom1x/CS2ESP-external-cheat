import sys
import os
import logging
import requests

# ================= ЛОГИРОВАНИЕ =================
logging.basicConfig(
    filename='debug.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    encoding='utf-8'
)

def log_error(msg):
    logging.error(msg)
    print(f"[!] Ошибка: {msg}. Смотри debug.log")

log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug.log")
logging.info("--- ЗАПУСК ЛОГГЕРА ---")

# ================= КОНФИГУРАЦИЯ =================
OFFSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offsets")
OFFSETS_FILE = os.path.join(OFFSETS_DIR, "offsets.json")
CLIENT_DLL_FILE = os.path.join(OFFSETS_DIR, "client_dll.json")

# ================= ПАТЧИНГ REQUESTS =================
original_get = requests.get

def patched_get(url, *args, **kwargs):
    # Перехват запросов к github для подмены на локальные файлы
    if "offsets.json" in url:
        if os.path.exists(OFFSETS_FILE):
            with open(OFFSETS_FILE, "r") as f:
                content = f.read()
            resp = requests.models.Response()
            resp._content = content.encode('utf-8')
            resp.status_code = 200
            logging.info(f"Загружены локальные офсеты из {OFFSETS_FILE}")
            return resp
        else:
            logging.error(f"Файл не найден: {OFFSETS_FILE}")
            
    elif "client_dll.json" in url:
        if os.path.exists(CLIENT_DLL_FILE):
            with open(CLIENT_DLL_FILE, "r") as f:
                content = f.read()
            resp = requests.models.Response()
            resp._content = content.encode('utf-8')
            resp.status_code = 200
            logging.info(f"Загружены локальные client_dll из {CLIENT_DLL_FILE}")
            return resp
        else:
            logging.error(f"Файл не найден: {CLIENT_DLL_FILE}")
            
    return original_get(url, *args, **kwargs)

# Применяем патч глобально
requests.get = patched_get
logging.info("Requests patched.")

# ================= ПРОВЕРКИ =================
if not os.path.exists(OFFSETS_DIR):
    msg = f"Папка {OFFSETS_DIR} не найдена. Создайте её."
    log_error(msg)
    sys.exit(1)

if not os.path.exists(OFFSETS_FILE) or not os.path.exists(CLIENT_DLL_FILE):
    msg = "Отсутствуют файлы JSON в папке /offsets/"
    log_error(msg)
    sys.exit(1)

# ================= ИМПОРТ И ЗАПУСК =================
try:
    logging.info("Попытка импорта CS2ESP...")
    import CS2ESP
    logging.info("Импорт успешен. Запуск main()...")
    CS2ESP.main()
except Exception as e:
    logging.exception("Критическая ошибка при выполнении CS2ESP:")
    print(f"[!] Фатальная ошибка. Проверь debug.log: {e}")
    input("Нажмите Enter, чтобы закрыть...")
