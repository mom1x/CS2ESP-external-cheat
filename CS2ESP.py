import os
import sys
import json
import time
import datetime
import ctypes
import struct
import warnings

warnings.filterwarnings("ignore", category=UserWarning, module='OpenGL')

# === ФИКС КОНСОЛИ: Принудительное создание CMD-окна ===
try:
    # Метод гарантирует, что даже внутри скомпилированного .exe откроется окно консоли
    ctypes.windll.kernel32.AllocConsole()
    sys.stdout = open("CONOUT$", "w", encoding="utf-8")
    sys.stderr = open("CONOUT$", "w", encoding="utf-8")
except Exception:
    pass

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE_PATH = os.path.join(BASE_DIR, "debug_log.txt")
LIVE_LOGS = ["Engine starting..."]

def log_message(level, message):
    """Логирование одновременно в файл, в созданную CMD консоль и в массив оверлея"""
    timestamp = datetime.datetime.now().strftime("%H:%M:%S")
    formatted_line = f"[{timestamp}] [{level.upper()}] {message}"
    
    print(formatted_line) # Печать в выделенное CMD окно
    
    # Добавляем в историю для вывода на экран игры (храним последние 6 строк)
    LIVE_LOGS.append(formatted_line)
    if len(LIVE_LOGS) > 6:
        LIVE_LOGS.pop(0)
        
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as log_file:
            log_file.write(f"[{datetime.datetime.now()}] [{level.upper()}] {message}\n")
    except:
        pass

# Сброс лога
try:
    with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
        f.write("=== CS2 PRO ESP ENGINE INITIALIZED ===\n\n")
except: pass

# Инициализация графических флагов
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except: pass

os.environ['PYOPENGL_PLATFORM'] = 'win32'
import OpenGL
OpenGL.ERROR_CHECKING = False
OpenGL.ERROR_LOGGING = False
import OpenGL.GL as gl

import pymem
import pymem.process
import glfw
import imgui
from imgui.integrations.glfw import GlfwRenderer

import win32api
import win32gui
import win32con

OpenProcess = ctypes.windll.kernel32.OpenProcess
ReadProcessMemory = ctypes.windll.kernel32.ReadProcessMemory
CloseHandle = ctypes.windll.kernel32.CloseHandle

class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

# =======================================================
# АВТОНОМНЫЙ ПАРСЕР ВНЕШНЕЙ ПАПКИ OFFSETS
# =======================================================
def load_offsets():
    conf = {
        "dwEntityList": 0, "dwViewMatrix": 0, "dwLocalPlayerPawn": 0,
        "m_iHealth": 0, "m_hPlayerPawn": 0, "m_vOldOrigin": 0, "m_iTeamNum": 0
    }
    
    offsets_dir = os.path.join(BASE_DIR, "offsets")
    offsets_path = os.path.join(offsets_dir, "offsets.json")
    client_dll_path = os.path.join(offsets_dir, "client_dll.json")

    log_message("info", f"Looking for offsets folder: {offsets_dir}")

    if not os.path.exists(offsets_path) or not os.path.exists(client_dll_path):
        log_message("critical", "CRITICAL ERROR: 'offsets' folder or JSON files not found next to script/exe!")
        return None

    try:
        with open(offsets_path, "r") as f:
            raw_offsets = json.load(f)["client.dll"]
        with open(client_dll_path, "r") as f:
            raw_classes = json.load(f)["client.dll"]["classes"]

        conf["dwEntityList"] = raw_offsets.get("dwEntityList", 0)
        conf["dwViewMatrix"] = raw_offsets.get("dwViewMatrix", 0)
        conf["dwLocalPlayerPawn"] = raw_offsets.get("dwLocalPlayerPawn", 0)

        def parse_val(d): return d.get("value", d.get("offset", 0)) if isinstance(d, dict) else d

        for cls in ["C_BaseEntity", "C_BasePlayerPawn", "CCSPlayerController", "C_CSPlayerPawnBase"]:
            if cls in raw_classes:
                fields = raw_classes[cls].get("fields", {})
                if "m_iHealth" in fields: conf["m_iHealth"] = parse_val(fields["m_iHealth"])
                if "m_hPlayerPawn" in fields: conf["m_hPlayerPawn"] = parse_val(fields["m_hPlayerPawn"])
                if "m_vOldOrigin" in fields: conf["m_vOldOrigin"] = parse_val(fields["m_vOldOrigin"])
                if "m_iTeamNum" in fields: conf["m_iTeamNum"] = parse_val(fields["m_iTeamNum"])
        
        log_message("info", "Offsets successfully parsed:")
        for k, v in conf.items():
            log_message("info", f"  -> {k}: {hex(v)}")
            
    except Exception as e:
        log_message("critical", f"JSON parsing error: {e}")
        return None
        
    return conf

# =======================================================
# СТАБИЛЬНЫЕ СИС-ВЫЗОВЫ С ПРОВЕРКОЙ ВАЛИДНОСТИ АДРЕСОВ
# =======================================================
def read_raw(handle, address, size):
    if address < 0x100000 or address > 0xF00000000000: # Проверка на выход за лимиты адресного пространства
        return None
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t()
    if ReadProcessMemory(handle, ctypes.c_void_p(address), buffer, size, ctypes.byref(bytes_read)):
        return buffer.raw
    return None

def read_int(handle, address):
    res = read_raw(handle, address, 4)
    return struct.unpack('i', res)[0] if res else 0

def read_uint(handle, address):
    res = read_raw(handle, address, 4)
    return struct.unpack('I', res)[0] if res else 0

def read_longlong(handle, address):
    res = read_raw(handle, address, 8)
    return struct.unpack('q', res)[0] if res else 0

def world_to_screen(pos, matrix, width, height):
    w = matrix[12] * pos[0] + matrix[13] * pos[1] + matrix[14] * pos[2] + matrix[15]
    if w < 0.01: return None
    x = matrix[0] * pos[0] + matrix[1] * pos[1] + matrix[2] * pos[2] + matrix[3]
    y = matrix[4] * pos[0] + matrix[5] * pos[1] + matrix[6] * pos[2] + matrix[7]
    return (width / 2) + (x / w) * (width / 2), (height / 2) - (y / w) * (height / 2)

def init_overlay():
    if not glfw.init():
        log_message("critical", "Failed to init GLFW Engine.")
        return None
        
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)

    screen_w = win32api.GetSystemMetrics(0)
    screen_h = win32api.GetSystemMetrics(1)
    if screen_w == 0 or screen_h == 0: screen_w, screen_h = 1920, 1080

    window = glfw.create_window(screen_w, screen_h, "CS2_PRO_OVERLAY", None, None)
    if not window:
        glfw.terminate()
        return None
    glfw.make_context_current(window)
    glfw.swap_interval(1)
    
    hwnd = glfw.get_win32_window(window)
    ex_style = win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

    try:
        dwmapi = ctypes.WinDLL('dwmapi')
        margins = MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
    except: pass

    imgui.create_context()
    renderer = GlfwRenderer(window)
    return window, renderer, hwnd, screen_w, screen_h

def main():
    log_message("info", "Starting up. Loading settings...")
    conf = load_offsets()
    if not conf:
        log_message("critical", "Initialization aborted due to missing configs.")
        time.sleep(5)
        return

    process_handle = None
    client_dll = None
    
    window, renderer, hwnd, screen_w, screen_h = init_overlay()
    if not window: return

    PROCESS_VM_READ = 0x0010
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    
    last_topmost_check = time.time()
    last_diagnostic_time = time.time()
    
    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()
        
        if time.time() - last_topmost_check > 2.0:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            last_topmost_check = time.time()

        imgui.new_frame()
        imgui.set_next_window_size(float(screen_w), float(screen_h))
        imgui.set_next_window_position(0.0, 0.0)
        imgui.begin("PRO_HUD", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        draw_list = imgui.get_window_draw_list()
        
        # === ВЫВОД ДИАГНОСТИКИ ПРЯМО НА ЭКРАН ИГРЫ ===
        draw_list.add_text(20, 20, imgui.get_color_u32_rgba(0.0, 1.0, 1.0, 1.0), "=== CS2 DIAGNOSTIC OVERLAY PANEL ===")
        
        # Отрисовка "живых" логов в левом углу
        current_y = 40
        for live_log in LIVE_LOGS:
            draw_list.add_text(20, current_y, imgui.get_color_u32_rgba(0.9, 0.9, 0.9, 1.0), live_log)
            current_y += 18

        if not client_dll:
            draw_list.add_text(20, current_y + 10, imgui.get_color_u32_rgba(1.0, 0.6, 0.0, 1.0), "PROCESS STATUS: WAITING FOR CS2.EXE...")
            for proc in pymem.process.list_processes():
                if "cs2.exe" in str(proc.szExeFile).lower():
                    pid = proc.th32ProcessID
                    log_message("info", f"Found CS2 process! PID: {pid}. Hooking memory handle...")
                    
                    # Запрос дескриптора (Bypass UAC)
                    process_handle = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                    if process_handle:
                        try:
                            pm_temp = pymem.Pymem()
                            pm_temp.process_id = pid
                            pm_temp.process_handle = process_handle
                            client_dll = pymem.process.module_from_name(pm_temp.process_handle, "client.dll").lpBaseOfDll
                            log_message("info", f"Linked to client.dll at base address: {hex(client_dll)}")
                        except Exception as ex:
                            log_message("error", f"Module mapping failed: {ex}")
                            client_dll = None
                    else:
                        log_message("critical", "Handle rejection! Windows anti-cheat hooks blocked User-Mode link.")
        else:
            draw_list.add_text(20, current_y + 10, imgui.get_color_u32_rgba(0.0, 1.0, 0.0, 1.0), "PROCESS STATUS: CONNECTED AND SCANNING")
            
            targets_count = 0
            
            try:
                # Читаем матрицу
                matrix_bytes = read_raw(process_handle, client_dll + conf["dwViewMatrix"], 64)
                entity_list = read_longlong(process_handle, client_dll + conf["dwEntityList"])
                
                local_team = -1
                local_pawn = read_longlong(process_handle, client_dll + conf["dwLocalPlayerPawn"])
                if local_pawn:
                    local_team = read_int(process_handle, local_pawn + conf["m_iTeamNum"])

                if matrix_bytes and entity_list:
                    view_matrix = list(struct.unpack('16f', matrix_bytes))
                    
                    # Сканируем массив сущностей
                    for i in range(1, 64):
                        # ФИКС ПРИОРИТЕТА ОПЕРАЦИЙ (Строго сгруппированные скобки для Source 2 в Python)
                        list_entry = read_longlong(process_handle, entity_list + (8 * ((i & 0x7FFF) >> 9)) + 16)
                        if not list_entry: continue
                        
                        controller = read_longlong(process_handle, list_entry + (120 * (i & 0x1FF)))
                        if not controller: continue
                        
                        pawn_handle = read_uint(process_handle, controller + conf["m_hPlayerPawn"])
                        if not pawn_handle: continue

                        # Повторный фикс для цепочки Павна
                        list_entry_pawn = read_longlong(process_handle, entity_list + (8 * ((pawn_handle & 0x7FFF) >> 9)) + 16)
                        if not list_entry_pawn: continue
                        
                        pawn_ptr = read_longlong(process_handle, list_entry_pawn + (120 * (pawn_handle & 0x1FF)))
                        if not pawn_ptr or pawn_ptr == local_pawn: continue

                        health = read_int(process_handle, pawn_ptr + conf["m_iHealth"])
                        if health <= 0 or health > 100: continue
                        
                        team = read_int(process_handle, pawn_ptr + conf["m_iTeamNum"])
                        
                        coords = read_raw(process_handle, pawn_ptr + conf["m_vOldOrigin"], 12)
                        if not coords: continue
                        x, y, z = struct.unpack('3f', coords)

                        screen_pos = world_to_screen([x, y, z], view_matrix, screen_w, screen_h)
                        head_pos = world_to_screen([x, y, z + 72.0], view_matrix, screen_w, screen_h)

                        if screen_pos and head_pos:
                            targets_count += 1
                            sc_x, sc_y = screen_pos
                            _, h_y = head_pos
                            
                            box_h = max(4.0, sc_y - h_y)
                            box_w = box_h / 1.9
                            
                            # Настройка цветов: Враг - Красный, Союзник - Голубой
                            color = imgui.get_color_u32_rgba(0.1, 0.6, 1.0, 1.0) if team == local_team else imgui.get_color_u32_rgba(1.0, 0.1, 0.1, 1.0)
                            draw_list.add_rect(sc_x - box_w/2, h_y, sc_x + box_w/2, sc_y, color, 0.0, 0, 1.5)

                            # Хитбар
                            hp_p = health / 100.0
                            hp_color = imgui.get_color_u32_rgba(1.0 - hp_p, hp_p, 0.0, 1.0)
                            hp_h = box_h * hp_p
                            
                            draw_list.add_rect_filled(sc_x - box_w/2 - 6, h_y, sc_x - box_w/2 - 2, sc_y, imgui.get_color_u32_rgba(0.0, 0.0, 0.0, 0.5))
                            draw_list.add_rect_filled(sc_x - box_w/2 - 5, sc_y - hp_h, sc_x - box_w/2 - 3, sc_y, hp_color)
                            
                else:
                    if time.time() - last_diagnostic_time > 4.0:
                        log_message("warning", "Matrix data or Entity List pointer is blank. Waiting for match load...")
                        last_diagnostic_time = time.time()
                        
            except Exception as loop_ex:
                log_message("error", f"Loop exception: {loop_ex}")
                client_dll = None
                process_handle = None

            draw_list.add_text(20, current_y + 30, imgui.get_color_u32_rgba(1.0, 1.0, 0.0, 1.0), f"VISIBLE TARGETS ON SCREEN: {targets_count}")

        imgui.end()
        
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        renderer.render(imgui.get_draw_data())
        glfw.swap_buffers(window)

    if process_handle:
        CloseHandle(process_handle)
    renderer.shutdown()
    glfw.terminate()

if __name__ == "__main__":
    main()
