import sys, os, traceback, datetime

# Логирование ошибок
log_file = open(os.path.join(os.path.dirname(sys.executable), "cs2esp_errors.log"), "a", encoding="utf-8")
def log_error(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file.write(f"[{timestamp}] {msg}\n")
    log_file.flush()

# Патчим класс Pymem на безопасное чтение
import pymem

original_read_longlong = pymem.Pymem.read_longlong
original_read_int = pymem.Pymem.read_int
original_read_float = pymem.Pymem.read_float

def safe_read_longlong(self, address):
    try:
        if address < 0x10000 or address > 0x7FFFFFFFFFFF:
            raise ValueError(f"Invalid address: {hex(address)}")
        return original_read_longlong(self, address)
    except Exception as e:
        log_error(f"read_longlong failed at {hex(address)}: {e}")
        return 0

def safe_read_int(self, address):
    try:
        if address < 0x10000 or address > 0x7FFFFFFFFFFF:
            raise ValueError(f"Invalid address: {hex(address)}")
        return original_read_int(self, address)
    except Exception as e:
        log_error(f"read_int failed at {hex(address)}: {e}")
        return 0

def safe_read_float(self, address):
    try:
        if address < 0x10000 or address > 0x7FFFFFFFFFFF:
            raise ValueError(f"Invalid address: {hex(address)}")
        return original_read_float(self, address)
    except Exception as e:
        log_error(f"read_float failed at {hex(address)}: {e}")
        return 0.0

pymem.Pymem.read_longlong = safe_read_longlong
pymem.Pymem.read_int = safe_read_int
pymem.Pymem.read_float = safe_read_float

# Запуск оригинального чита
import CS2ESP
CS2ESP.main()
