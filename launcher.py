import sys, os, json, requests, pymem, datetime, struct, re

# ================= ЛОГИРОВАНИЕ =================
log_path = os.path.join(os.path.dirname(sys.executable), "cs2esp_errors.log")
log_file = open(log_path, "a", encoding="utf-8")
def log(msg):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_file.write(f"[{ts}] {msg}\n")
    log_file.flush()

# ================= УМНЫЙ ПОИСК ОФФСЕТОВ =================
OFFSETS_DIR = os.path.join(os.path.dirname(sys.executable), "offsets")
os.makedirs(OFFSETS_DIR, exist_ok=True)

def is_valid_offsets(offs, client):
    try:
        return (offs['client.dll']['dwEntityList'] > 0x1000 and
                offs['client.dll']['dwLocalPlayerPawn'] > 0x1000 and
                offs['client.dll']['dwViewMatrix'] > 0x1000)
    except:
        return False

def download_offsets():
    mirrors = [
        "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json",
        "https://raw.githubusercontent.com/TKazer/cs2-dumper/main/output/offsets.json",
        "https://raw.githubusercontent.com/CS2-OFFSETS/CS2-OFFSETS/main/offsets.json"
    ]
    for url in mirrors:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                offs = r.json()
                if is_valid_offsets(offs, offs):
                    with open(os.path.join(OFFSETS_DIR, "offsets.json"), "w") as f:
                        f.write(r.text)
                    log(f"Valid offsets from {url}")
                    return True
        except:
            continue
    return False

def download_client_dll():
    mirrors = [
        "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json",
        "https://raw.githubusercontent.com/TKazer/cs2-dumper/main/output/client_dll.json",
        "https://raw.githubusercontent.com/CS2-OFFSETS/CS2-OFFSETS/main/client_dll.json"
    ]
    for url in mirrors:
        try:
            r = requests.get(url, timeout=5)
            if r.status_code == 200:
                with open(os.path.join(OFFSETS_DIR, "client_dll.json"), "w") as f:
                    f.write(r.text)
                log(f"client_dll.json from {url}")
                return True
        except:
            continue
    return False

# Попытка скачать готовые JSON
downloaded = download_offsets() and download_client_dll()

# Если не удалось – вычисляем оффсеты через сигнатуры в памяти
if not downloaded:
    log("Download failed, using signature scanning...")
    try:
        pm = pymem.Pymem("cs2.exe")
    except:
        log("Can't open cs2.exe - run the game first!")
        sys.exit(1)

    import pymem.process
    client_mod = pymem.process.module_from_name(pm.process_handle, "client.dll")
    client = client_mod.lpBaseOfDll
    size = client_mod.SizeOfImage
    data = pm.read_bytes(client, size)

    def pattern_scan(module_data, pattern):
        pat = bytes.fromhex(pattern.replace(" ", ""))
        mask = pattern.replace(" ", "").replace("?", "\\x00")
        # просто ищем последовательность байтов, игнорируя '?' как любой байт
        scan = module_data
        for i in range(len(scan) - len(pat)):
            match = True
            for j in range(len(pat)):
                if pattern.split()[j] != "?" and scan[i+j] != pat[j]:
                    match = False
                    break
            if match:
                return i
        return None

    # Актуальные сигнатуры (можно уточнить на GitHub)
    sig_dwEntityList = "48 8B 0D ? ? ? ? 48 8B 14 C1 48 85 D2 74 ? 8B 42 ?"
    sig_dwLocalPlayerPawn = "48 8B 05 ? ? ? ? 48 85 C0 74 ? 8B 80 ? ? ? ?"
    sig_dwViewMatrix = "48 8D 0D ? ? ? ? 48 8B D6 48 C1 E2 05"

    def resolve_rip(addr):
        # rip-relative смещение по адресу addr + 3 (для инструкций с disp32)
        disp = struct.unpack("<i", data[addr+3:addr+7])[0]
        return client + addr + 7 + disp

    ent_off = pattern_scan(data, sig_dwEntityList)
    lp_off = pattern_scan(data, sig_dwLocalPlayerPawn)
    vm_off = pattern_scan(data, sig_dwViewMatrix)

    if not all([ent_off, lp_off, vm_off]):
        log("Signature scan failed. Offsets not found.")
        sys.exit(1)

    dwEntityList = resolve_rip(ent_off)
    dwLocalPlayerPawn = resolve_rip(lp_off)
    dwViewMatrix = resolve_rip(vm_off)

    log(f"Scanned offsets: ent={hex(dwEntityList)}, lp={hex(dwLocalPlayerPawn)}, vm={hex(dwViewMatrix)}")

    # Формируем свой offsets.json
    fake_offsets = {
        "client.dll": {
            "dwEntityList": dwEntityList,
            "dwLocalPlayerPawn": dwLocalPlayerPawn,
            "dwViewMatrix": dwViewMatrix
        }
    }
    with open(os.path.join(OFFSETS_DIR, "offsets.json"), "w") as f:
        json.dump(fake_offsets, f, indent=2)

    # Поля для client_dll.json тоже можно просканировать, но проще заглушить
    fake_client = {
        "client.dll": {
            "classes": {
                "C_BaseEntity": {
                    "fields": {
                        "m_iTeamNum": 0x3E4,
                        "m_lifeState": 0x2A0,
                        "m_pGameSceneNode": 0x338,
                        "m_iHealth": 0x3D0
                    }
                },
                "CSkeletonInstance": {
                    "fields": {
                        "m_modelState": 0x240
                    }
                },
                "CCSPlayerController": {
                    "fields": {
                        "m_hPlayerPawn": 0x7F4
                    }
                }
            }
        }
    }
    with open(os.path.join(OFFSETS_DIR, "client_dll.json"), "w") as f:
        json.dump(fake_client, f, indent=2)
    log("Generated local JSON from memory signatures.")
    pm.close()

# ================= ПЕРЕХВАТ ЗАГРУЗКИ ОФФСЕТОВ =================
original_get = requests.get
def patched_get(url, *args, **kwargs):
    if "offsets.json" in url and "a2x" in url:
        p = os.path.join(OFFSETS_DIR, "offsets.json")
    elif "client_dll.json" in url and "a2x" in url:
        p = os.path.join(OFFSETS_DIR, "client_dll.json")
    else:
        return original_get(url, *args, **kwargs)
    if os.path.exists(p):
        with open(p, "r") as f:
            content = f.read()
        resp = requests.models.Response()
        resp._content = content.encode('utf-8')
        resp.status_code = 200
        return resp
    return original_get(url, *args, **kwargs)
requests.get = patched_get

# ================= ЗАЩИТА pymem =================
orig_longlong = pymem.Pymem.read_longlong
orig_int = pymem.Pymem.read_int
orig_float = pymem.Pymem.read_float

def safe_read_longlong(self, addr):
    try:
        if addr < 0x10000 or addr > 0x7FFFFFFFFFFF:
            raise ValueError(f"Invalid address: {hex(addr)}")
        return orig_longlong(self, addr)
    except Exception as e:
        log(f"read_longlong failed at {hex(addr)}: {e}")
        return 0

def safe_read_int(self, addr):
    try:
        if addr < 0x10000 or addr > 0x7FFFFFFFFFFF:
            raise ValueError(f"Invalid address: {hex(addr)}")
        return orig_int(self, addr)
    except Exception as e:
        log(f"read_int failed at {hex(addr)}: {e}")
        return 0

def safe_read_float(self, addr):
    try:
        if addr < 0x10000 or addr > 0x7FFFFFFFFFFF:
            raise ValueError(f"Invalid address: {hex(addr)}")
        return orig_float(self, addr)
    except Exception as e:
        log(f"read_float failed at {hex(addr)}: {e}")
        return 0.0

pymem.Pymem.read_longlong = safe_read_longlong
pymem.Pymem.read_int = safe_read_int
pymem.Pymem.read_float = safe_read_float

# ================= ЗАПУСК =================
import CS2ESP
CS2ESP.main()
