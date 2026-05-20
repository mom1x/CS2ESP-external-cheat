import os, sys, json, time, ctypes, struct, warnings
import pymem, pymem.process
# Убедитесь, что requirements.txt содержит все нужные библиотеки

# --- НАСТРОЙКИ ---
warnings.filterwarnings("ignore")
try:
    ctypes.windll.kernel32.AllocConsole()
    sys.stdout = open("CONOUT$", "w", encoding="utf-8")
except: pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def read_longlong(handle, address):
    if not address or address < 0x1000: return 0
    buf = ctypes.create_string_buffer(8)
    if ctypes.windll.kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, 8, None):
        return struct.unpack('q', buf.raw)[0]
    return 0

def read_uint(handle, address):
    if not address or address < 0x1000: return 0
    buf = ctypes.create_string_buffer(4)
    if ctypes.windll.kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, 4, None):
        return struct.unpack('I', buf.raw)[0]
    return 0

def read_int(handle, address):
    if not address or address < 0x1000: return 0
    buf = ctypes.create_string_buffer(4)
    if ctypes.windll.kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, 4, None):
        return struct.unpack('i', buf.raw)[0]
    return 0

def load_offsets():
    # Загрузка... (ваш код загрузки)
    try:
        with open(os.path.join(BASE_DIR, "offsets/offsets.json"), "r") as f:
            off = json.load(f)["client.dll"]
        with open(os.path.join(BASE_DIR, "offsets/client_dll.json"), "r") as f:
            cls = json.load(f)["client.dll"]["classes"]
        return {
            "dwEntityList": off["dwEntityList"],
            "dwLocalPlayerPawn": off["dwLocalPlayerPawn"],
            "m_hPlayerPawn": cls["CCSPlayerController"]["fields"]["m_hPlayerPawn"]["value"],
            "m_iHealth": cls["C_BaseEntity"]["fields"]["m_iHealth"]["value"]
        }
    except Exception as e:
        print(f"Error loading JSON: {e}")
        return None

def main():
    conf = load_offsets()
    if not conf: return

    # Ищем процесс
    pid = 0
    client_dll = 0
    for p in pymem.process.list_processes():
        if "cs2.exe" in p.szExeFile.decode().lower():
            pid = p.th32ProcessID
            handle = ctypes.windll.kernel32.OpenProcess(0x10 | 0x1000, False, pid)
            pm = pymem.Pymem()
            pm.process_id = pid
            client_dll = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
            break
    
    if not client_dll:
        print("CS2 не найден!")
        return

    print(f"Подключено. База: {hex(client_dll)}")

    while True:
        targets = 0
        
        # 1. Читаем EntityList
        entity_list = read_longlong(handle, client_dll + conf["dwEntityList"])
        if not entity_list:
            print("Ошибка: EntityList не найден (проверьте офсет dwEntityList)")
            time.sleep(2)
            continue
            
        # 2. Локальный игрок
        local_pawn = read_longlong(handle, client_dll + conf["dwLocalPlayerPawn"])
        
        # 3. Перебор
        for i in range(1, 64):
            list_entry = read_longlong(handle, entity_list + (8 * ((i & 0x7FFF) >> 9) + 16))
            if not list_entry: continue
            
            controller = read_longlong(handle, list_entry + (120 * (i & 0x1FF)))
            if not controller: continue
            
            pawn_handle = read_uint(handle, controller + conf["m_hPlayerPawn"])
            if not pawn_handle: continue
            
            list_entry_pawn = read_longlong(handle, entity_list + 0x8 * ((pawn_handle & 0x7FFF) >> 9) + 16)
            if not list_entry_pawn: continue
            
            pawn_ptr = read_longlong(handle, list_entry_pawn + (120 * (pawn_handle & 0x1FF)))
            
            if pawn_ptr and pawn_ptr != local_pawn:
                health = read_int(handle, pawn_ptr + conf["m_iHealth"])
                if 0 < health <= 100:
                    targets += 1
        
        print(f"Targets found: {targets}", end='\r')
        time.sleep(1)

if __name__ == "__main__":
    main()
