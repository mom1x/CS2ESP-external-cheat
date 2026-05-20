import os
import sys
import json
import time
import datetime
import ctypes
import struct
import warnings
import numpy as np  # Исправлено: numpy обязателен для PyOpenGL

# Окружение
os.environ['PYOPENGL_PLATFORM'] = 'win32'
warnings.filterwarnings("ignore", category=UserWarning, module='OpenGL')

# Инициализация консоли
try:
    ctypes.windll.kernel32.AllocConsole()
    sys.stdout = open("CONOUT$", "w", encoding="utf-8")
    sys.stderr = open("CONOUT$", "w", encoding="utf-8")
except: pass

# Импорты после инициализации
import pymem
import pymem.process
import glfw
import imgui
from imgui.integrations.glfw import GlfwRenderer
import OpenGL.GL as gl
import win32api
import win32gui
import win32con

# Структуры для Windows API
class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

# Глобальные настройки
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE_PATH = os.path.join(BASE_DIR, "debug_log.txt")
LIVE_LOGS = ["Engine Starting..."]

def log_message(level, message):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    formatted = f"[{ts}] [{level.upper()}] {message}"
    print(formatted)
    LIVE_LOGS.append(formatted)
    if len(LIVE_LOGS) > 8: LIVE_LOGS.pop(0)

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

# --- Математика ---
def world_to_screen(pos, matrix, w_scr, h_scr):
    w = matrix[12] * pos[0] + matrix[13] * pos[1] + matrix[14] * pos[2] + matrix[15]
    if w < 0.01: return None
    x = matrix[0] * pos[0] + matrix[1] * pos[1] + matrix[2] * pos[2] + matrix[3]
    y = matrix[4] * pos[0] + matrix[5] * pos[1] + matrix[6] * pos[2] + matrix[7]
    return (w_scr / 2) + (x / w) * (w_scr / 2), (h_scr / 2) - (y / w) * (h_scr / 2)

def load_offsets():
    try:
        with open(os.path.join(BASE_DIR, "offsets/offsets.json"), "r") as f:
            off = json.load(f)["client.dll"]
        with open(os.path.join(BASE_DIR, "offsets/client_dll.json"), "r") as f:
            cls = json.load(f)["client.dll"]["classes"]
        return {
            "dwEntityList": off["dwEntityList"],
            "dwViewMatrix": off["dwViewMatrix"],
            "dwLocalPlayerPawn": off["dwLocalPlayerPawn"],
            "m_iHealth": cls["C_BaseEntity"]["fields"]["m_iHealth"]["value"],
            "m_hPlayerPawn": cls["CCSPlayerController"]["fields"]["m_hPlayerPawn"]["value"],
            "m_vOldOrigin": cls["C_BasePlayerPawn"]["fields"]["m_vOldOrigin"]["value"],
            "m_iTeamNum": cls["C_BasePlayerPawn"]["fields"]["m_iTeamNum"]["value"]
        }
    except Exception as e:
        log_message("critical", f"JSON Load Error: {e}")
        return None

def init_overlay():
    if not glfw.init(): return None
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)
    w, h = win32api.GetSystemMetrics(0), win32api.GetSystemMetrics(1)
    window = glfw.create_window(w, h, "CS2_ESP", None, None)
    glfw.make_context_current(window)
    hwnd = glfw.get_win32_window(window)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST)
    imgui.create_context()
    return window, GlfwRenderer(window), w, h

def main():
    conf = load_offsets()
    if not conf: return
    
    window, renderer, w_scr, h_scr = init_overlay()
    process_handle, client_dll = None, None

    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()
        
        # Поиск процесса
        if not client_dll:
            for proc in pymem.process.list_processes():
                if "cs2.exe" in str(proc.szExeFile).lower():
                    pid = proc.th32ProcessID
                    process_handle = ctypes.windll.kernel32.OpenProcess(0x10 | 0x1000, False, pid)
                    pm = pymem.Pymem()
                    pm.process_id = pid
                    try:
                        client_dll = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
                        log_message("info", f"Connected. Base: {hex(client_dll)}")
                    except: pass
                    break

        imgui.new_frame()
        imgui.set_next_window_size(float(w_scr), float(h_scr))
        imgui.set_next_window_position(0.0, 0.0)
        imgui.begin("ESP", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        draw_list = imgui.get_window_draw_list()
        
        targets = 0
        if client_dll:
            try:
                matrix_raw = read_raw(process_handle, client_dll + conf["dwViewMatrix"], 64)
                view_matrix = list(struct.unpack('16f', matrix_raw))
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
                            # Здесь будет ваша отрисовка (add_rect и т.д.)
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
