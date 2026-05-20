import sys
import os
import logging
import requests
import pymem
import pymem.process
import ctypes

# ================= 1. НАСТРОЙКИ ПУТЕЙ =================
BASE_DIR = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "debug.log")
OFFSETS_DIR = os.path.join(BASE_DIR, "offsets")
OFFSETS_FILE = os.path.join(OFFSETS_DIR, "offsets.json")
CLIENT_DLL_FILE = os.path.join(OFFSETS_DIR, "client_dll.json")

# ================= 2. ЛОГИРОВАНИЕ =================
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - %(message)s',
    encoding='utf-8',
    filemode='w' # Перезаписывать лог при каждом запуске
)
logging.info(f"Запуск в директории: {BASE_DIR}")

# ================= 3. САНИТАЙЗЕР ПАМЯТИ (FIX 998) =================
def sanitize_addr(addr):
    # Принудительное приведение к unsigned 64-bit
    addr = addr & 0xFFFFFFFFFFFFFFFF
    # Проверка на валидность адреса (диапазон памяти процесса)
    if addr < 0x10000 or addr > 0x7FFFFFFFFFFF:
        return None
    return addr

# Сохраняем оригинальные методы
orig_read_longlong = pymem.Pymem.read_longlong
orig_read_int = pymem.Pymem.read_int
orig_read_float = pymem.Pymem.read_float

def safe_read_longlong(self, addr):
    s_addr = sanitize_addr(addr)
    if s_addr is None: return 0
    try: return orig_read_longlong(self, s_addr)
    except: return 0

def safe_read_int(self, addr):
    s_addr = sanitize_addr(addr)
    if s_addr is None: return 0
    try: return orig_read_int(self, s_addr)
    except: return 0

def safe_read_float(self, addr):
    s_addr = sanitize_addr(addr)
    if s_addr is None: return 0.0
    try: return orig_read_float(self, s_addr)
    except: return 0.0

pymem.Pymem.read_longlong = safe_read_longlong
pymem.Pymem.read_int = safe_read_int
pymem.Pymem.read_float = safe_read_float

# ================= 4. ПАТЧИНГ ЗАПРОСОВ (MONKEY PATCHING) =================
original_get = requests.get

def patched_get(url, *args, **kwargs):
    if "offsets.json" in url and os.path.exists(OFFSETS_FILE):
        with open(OFFSETS_FILE, "r") as f: content = f.read()
        resp = requests.models.Response()
        resp._content = content.encode('utf-8')
        resp.status_code = 200
        return resp
    elif "client_dll.json" in url and os.path.exists(CLIENT_DLL_FILE):
        with open(CLIENT_DLL_FILE, "r") as f: content = f.read()
        resp = requests.models.Response()
        resp._content = content.encode('utf-8')
        resp.status_code = 200
        return resp
    return original_get(url, *args, **kwargs)

requests.get = patched_get

# ================= 5. ПРОВЕРКА ФАЙЛОВ =================
if not os.path.exists(OFFSETS_DIR):
    logging.error(f"Папка {OFFSETS_DIR} не найдена.")
    sys.exit(1)

if not os.path.exists(OFFSETS_FILE) or not os.path.exists(CLIENT_DLL_FILE):
    logging.error("Файлы JSON не найдены в папке /offsets/")
    sys.exit(1)

# ================= 6. ЗАПУСК =================
try:
    logging.info("Импорт CS2ESP...")
    import CS2ESP
    logging.info("Импорт успешен. Старт main().")
    CS2ESP.main()
except Exception as e:
    logging.critical(f"Критический сбой: {e}", exc_info=True)
    sys.exit(1)
