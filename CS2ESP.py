import os
import sys
import json
import time
import datetime
import ctypes
import struct
import warnings

# --- Обязательные импорты ---
import numpy as np 
import pymem
import pymem.process
import glfw
import imgui
from imgui.integrations.glfw import GlfwRenderer
import OpenGL.GL as gl
import win32api
import win32gui
import win32con

# --- Настройки ---
os.environ['PYOPENGL_PLATFORM'] = 'win32'
warnings.filterwarnings("ignore", category=UserWarning, module='OpenGL')

# Инициализация консоли для exe
try:
    ctypes.windll.kernel32.AllocConsole()
    sys.stdout = open("CONOUT$", "w", encoding="utf-8")
    sys.stderr = open("CONOUT$", "w", encoding="utf-8")
except: pass

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

LOG_FILE_PATH = os.path.join(BASE_DIR, "debug_log.txt")

def log_message(level, message):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    formatted = f"[{ts}] [{level.upper()}] {message}"
    print(formatted)
    try:
        with open(LOG_FILE_PATH, "a", encoding="utf-8") as f:
            f.write(formatted + "\n")
    except: pass

# --- Функции чтения памяти ---
def read_raw(handle, address, size):
    if not address or address < 0x1000: return None
    buf = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t()
    if ctypes.windll.kernel32.ReadProcessMemory(handle, ctypes.c_void_p(address), buf, size, ctypes.byref(bytes_read)):
        return buf.raw
    return None

def read_longlong(handle, address):
    res = read_raw(handle, address, 8)
    return struct.unpack('q', res)[0] if res else 0

def read_int(handle, address):
    res = read_raw(handle, address, 4)
    return struct.unpack('i', res)[0] if res else 0

def read_uint(handle, address):
    res = read_raw(handle, address, 4)
    return struct.unpack('I', res)[0] if res else 0

# --- Безопасная загрузка офсетов ---
def load_offsets():
    offsets_dir = os.path.join(BASE_DIR, "offsets")
    off_path = os.path.join(offsets_dir, "offsets.json")
    cls_path = os.path.join(offsets_dir, "client_dll.json")
    
    # Вспомогательная функция для парсинга
    def get_val(data, key):
        field = data.get(key)
        if field is None: return 0
        # Если значение в JSON — словарь, ищем value или offset
        if isinstance(field, dict):
            return field.get("value", field.get("offset", 0))
        # Если это просто число (int), возвращаем его
        return field

    if not os.path.exists(off_path) or not os.path.exists(cls_path):
        log_message("critical", f"JSON FILES NOT FOUND in {offsets_dir}")
        return None

    try:
        with open(off_path, "r", encoding="utf-8") as f:
            raw_offsets = json.load(f)["client.dll"]
        with open(cls_path, "r", encoding="utf-8") as f:
            raw_classes = json.load(f)["client.dll"]["classes"]
            
        fields_base = raw_classes.get("C_BaseEntity", {}).get("fields", {})
        fields_controller = raw_classes.get("CCSPlayerController", {}).get("fields", {})
        fields_pawn = raw_classes.get("C_BasePlayerPawn", {}).get("fields", {})
            
        return {
            "dwEntityList": raw_offsets.get("dwEntityList", 0),
            "dwViewMatrix": raw_offsets.get("dwViewMatrix", 0),
            "dwLocalPlayerPawn": raw_offsets.get("dwLocalPlayerPawn", 0),
            "m_iHealth": get_val(fields_base, "m_iHealth"),
            "m_hPlayerPawn": get_val(fields_controller, "m_hPlayerPawn"),
            "m_vOldOrigin": get_val(fields_pawn, "m_vOldOrigin"),
            "m_iTeamNum": get_val(fields_pawn, "m_iTeamNum")
        }
    except Exception as e:
        log_message("critical", f"JSON Load Error: {e}")
        return None

# --- Инициализация Оверлея ---
def init_overlay():
    if not glfw.init(): return None
    w, h = win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)
    window = glfw.create_window(w, h, "CS2_ESP", None, None)
    glfw.make_context_current(window)
    hwnd = glfw.get_win32_window(window)
    ex_style = win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    imgui.create_context()
    return window, GlfwRenderer(window), w, h

# --- Основной цикл ---
def main():
    conf = load_offsets()
    if not conf:
        time.sleep(5)
        return

    window, renderer, w_scr, h_scr = init_overlay()
    process_handle, client_dll = None, None

    log_message("info", "ESP active. Waiting for CS2...")

    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()

        if not client_dll:
            for proc in pymem.process.list_processes():
                if "cs2.exe" in str(proc.szExeFile).lower():
                    pid = proc.th32ProcessID
                    process_handle = ctypes.windll.kernel32.OpenProcess(0x10 | 0x1000, False, pid)
                    pm = pymem.Pymem()
                    pm.process_id = pid
                    try:
                        client_dll = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
                        log_message("info", f"Linked to CS2. Base: {hex(client_dll)}")
                    except: pass
                    break

        imgui.new_frame()
        imgui.set_next_window_size(float(w_scr), float(h_scr))
        imgui.set_next_window_position(0.0, 0.0)
        imgui.begin("ESP_OVERLAY", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        draw_list = imgui.get_window_draw_list()
        
        targets = 0
        if client_dll and process_handle:
            try:
                entity_list = read_longlong(process_handle, client_dll + conf["dwEntityList"])
                local_pawn = read_longlong(process_handle, client_dll + conf["dwLocalPlayerPawn"])
                
                for i in range(1, 64):
                    list_entry = read_longlong(process_handle, entity_list + (8 * ((i & 0x7FFF) >> 9) + 16))
                    if not list_entry: continue
                    controller = read_longlong(process_handle, list_entry + (120 * (i & 0x1FF)))
                    if not controller: continue
                    
                    pawn_handle = read_uint(process_handle, controller + conf["m_hPlayerPawn"])
                    if not pawn_handle: continue
                    
                    list_entry_pawn = read_longlong(process_handle, entity_list + 0x8 * ((pawn_handle & 0x7FFF) >> 9) + 16)
                    pawn_ptr = read_longlong(process_handle, list_entry_pawn + (120 * (pawn_handle & 0x1FF)))
                    
                    if pawn_ptr and pawn_ptr != local_pawn:
                        health = read_int(process_handle, pawn_ptr + conf["m_iHealth"])
                        if 0 < health <= 100:
                            targets += 1
            except: pass

        draw_list.add_text(20, 20, 0xFFFFFFFF, f"Targets: {targets}")
        imgui.end()
        
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        renderer.render(imgui.get_draw_data())
        glfw.swap_buffers(window)

    renderer.shutdown()
    glfw.terminate()

if __name__ == "__main__":
    main()
