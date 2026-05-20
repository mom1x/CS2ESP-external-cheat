import sys
import os
import logging
import requests
import pymem
import pymem.process
import time

# ================= 1. НАСТРОЙКИ ЛОГОВ И ПУТЕЙ =================
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "debug.log")
OFFSETS_DIR = os.path.join(BASE_DIR, "offsets")
OFFSETS_FILE = os.path.join(OFFSETS_DIR, "offsets.json")
CLIENT_DLL_FILE = os.path.join(OFFSETS_DIR, "client_dll.json")

# Инициализация логирования (один раз на весь процесс)
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    encoding='utf-8',
    filemode='w'
)
logging.info(f"Launcher запущен. Папка: {BASE_DIR}")

# ================= 2. САНИТАЙЗЕР ПАМЯТИ (FIX 998) =================
def sanitize_addr(addr):
    addr = addr & 0xFFFFFFFFFFFFFFFF
    if addr < 0x10000 or addr > 0x7FFFFFFFFFFF: return None
    return addr

orig_read_longlong = pymem.Pymem.read_longlong
orig_read_int = pymem.Pymem.read_int
orig_read_float = pymem.Pymem.read_float

def safe_read_longlong(self, addr):
    s_addr = sanitize_addr(addr)
    return orig_read_longlong(self, s_addr) if s_addr else 0

def safe_read_int(self, addr):
    s_addr = sanitize_addr(addr)
    return orig_read_int(self, s_addr) if s_addr else 0

def safe_read_float(self, addr):
    s_addr = sanitize_addr(addr)
    return orig_read_float(self, s_addr) if s_addr else 0.0

pymem.Pymem.read_longlong = safe_read_longlong
pymem.Pymem.read_int = safe_read_int
pymem.Pymem.read_float = safe_read_float
logging.info("Патчи памяти pymem применены.")

# ================= 3. ПАТЧИНГ ЗАПРОСОВ =================
original_get = requests.get

def patched_get(url, *args, **kwargs):
    if "offsets.json" in url:
        logging.info("Перехват запроса offsets.json")
        with open(OFFSETS_FILE, "r") as f: content = f.read()
        resp = requests.models.Response()
        resp._content = content.encode('utf-8')
        resp.status_code = 200
        return resp
    elif "client_dll.json" in url:
        logging.info("Перехват запроса client_dll.json")
        with open(CLIENT_DLL_FILE, "r") as f: content = f.read()
        resp = requests.models.Response()
        resp._content = content.encode('utf-8')
        resp.status_code = 200
        return resp
    return original_get(url, *args, **kwargs)

requests.get = patched_get

# ================= 4. ПРОВЕРКА СРЕДЫ =================
if not os.path.exists(OFFSETS_FILE) or not os.path.exists(CLIENT_DLL_FILE):
    logging.critical("Файлы офсетов не найдены в папке /offsets/!")
    sys.exit(1)

# ================= 5. ЗАПУСК =================
try:
    logging.info("Импорт CS2ESP...")
    import CS2ESP
    # Если cs2.exe не запущен, CS2ESP может упасть сразу
    logging.info("Запуск CS2ESP.main()")
    CS2ESP.main()
except Exception as e:
    logging.critical(f"Ошибка выполнения CS2ESP: {e}", exc_info=True)
    sys.exit(1)
