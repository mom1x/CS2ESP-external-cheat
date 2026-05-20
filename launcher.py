import sys
import os
import json
import requests
import pymem
import datetime

# ================= ЛОГИРОВАНИЕ ОШИБОК =================
log_path = os.path.join(os.path.dirname(sys.executable), "cs2esp_errors.log")
log_file = open(log_path, "a", encoding="utf-8")
def log_error(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file.write(f"[{ts}] {msg}\n")
    log_file.flush()

# ================= АВТООБНОВЛЕНИЕ ОФФСЕТОВ =================
OFFSETS_DIR = os.path.join(os.path.dirname(sys.executable), "offsets")
os.makedirs(OFFSETS_DIR, exist_ok=True)

OFFSETS_URL = "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json"
CLIENT_DLL_URL = "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json"

def download_fresh_offsets():
    try:
        r = requests.get(OFFSETS_URL, timeout=5)
        if r.status_code == 200:
            with open(os.path.join(OFFSETS_DIR, "offsets.json"), "w", encoding="utf-8") as f:
                f.write(r.text)
            log_error("Successfully downloaded fresh offsets.json")
        else:
            log_error(f"Failed to download offsets.json, status {r.status_code}")
    except Exception as e:
        log_error(f"Exception downloading offsets.json: {e}")

    try:
        r = requests.get(CLIENT_DLL_URL, timeout=5)
        if r.status_code == 200:
            with open(os.path.join(OFFSETS_DIR, "client_dll.json"), "w", encoding="utf-8") as f:
                f.write(r.text)
            log_error("Successfully downloaded fresh client_dll.json")
        else:
            log_error(f"Failed to download client_dll.json, status {r.status_code}")
    except Exception as e:
        log_error(f"Exception downloading client_dll.json: {e}")

# Скачиваем актуальные JSON'ы при запуске (если есть интернет)
download_fresh_offsets()

# ================= ПЕРЕХВАТ ЗАГРУЗКИ ОФФСЕТОВ =================
original_get = requests.get
def patched_get(url, *args, **kwargs):
    if "raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json" in url:
        local_path = os.path.join(OFFSETS_DIR, "offsets.json")
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
            resp = requests.models.Response()
            resp._content = content.encode('utf-8')
            resp.status_code = 200
            return resp
        else:
            log_error(f"Local offsets.json not found at {local_path}")
    elif "raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json" in url:
        local_path = os.path.join(OFFSETS_DIR, "client_dll.json")
        if os.path.exists(local_path):
            with open(local_path, "r", encoding="utf-8") as f:
                content = f.read()
            resp = requests.models.Response()
            resp._content = content.encode('utf-8')
            resp.status_code = 200
            return resp
        else:
            log_error(f"Local client_dll.json not found at {local_path}")
    return original_get(url, *args, **kwargs)

requests.get = patched_get

# ================= ЗАЩИТА pymem ОТ БИТЫХ АДРЕСОВ =================
orig_read_longlong = pymem.Pymem.read_longlong
orig_read_int = pymem.Pymem.read_int
orig_read_float = pymem.Pymem.read_float

def safe_read_longlong(self, addr):
    try:
        if addr < 0x10000 or addr > 0x7FFFFFFFFFFF:
            raise ValueError(f"Invalid address: {hex(addr)}")
        return orig_read_longlong(self, addr)
    except Exception as e:
        log_error(f"read_longlong failed at {hex(addr)}: {e}")
        return 0

def safe_read_int(self, addr):
    try:
        if addr < 0x10000 or addr > 0x7FFFFFFFFFFF:
            raise ValueError(f"Invalid address: {hex(addr)}")
        return orig_read_int(self, addr)
    except Exception as e:
        log_error(f"read_int failed at {hex(addr)}: {e}")
        return 0

def safe_read_float(self, addr):
    try:
        if addr < 0x10000 or addr > 0x7FFFFFFFFFFF:
            raise ValueError(f"Invalid address: {hex(addr)}")
        return orig_read_float(self, addr)
    except Exception as e:
        log_error(f"read_float failed at {hex(addr)}: {e}")
        return 0.0

pymem.Pymem.read_longlong = safe_read_longlong
pymem.Pymem.read_int = safe_read_int
pymem.Pymem.read_float = safe_read_float

# ================= ЗАПУСК ЧИТА =================
import CS2ESP
CS2ESP.main()
