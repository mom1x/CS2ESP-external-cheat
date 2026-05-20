import os
import sys
import json
import time
import ctypes
import struct
import warnings
import urllib.request  # Для автоматического обновления оффсетов

warnings.filterwarnings("ignore", category=UserWarning, module='OpenGL')

# === НАСТРОЙКА DPI И ОКНА ===
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

class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

# ==============================================================================
# АВТОМАТИЧЕСКИЙ ДИНАМИЧЕСКИЙ ОБНОВЛЯТОР ОФФСЕТОВ (Через актуальные репозитории)
# ==============================================================================
def fetch_live_offsets():
    """
    Загружает свежие оффсеты напрямую из регулярно обновляемых дамперов сообщества.
    Это гарантирует работоспособность после патчей игры.
    """
    print("[SYSTEM] Fetching actual offsets from public repository...")
    base_conf = {
        "dwEntityList": 0x18C2DB8, 
        "dwViewMatrix": 0x19242A0, 
        "dwLocalPlayerPawn": 0x1823A08,
        "m_iHealth": 0x32C, 
        "m_hPlayerPawn": 0x7BC, 
        "m_vOldOrigin": 0x1274, 
        "m_iTeamNum": 0x3BF
    }
    
    try:
        # Используем доверенные JSON дампы, обновляемые автоматически каждым патчем CS2
        offsets_url = "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json"
        client_url = "https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json"
        
        req_offsets = urllib.request.urlopen(offsets_url, timeout=5)
        req_client = urllib.request.urlopen(client_url, timeout=5)
        
        offsets_data = json.loads(req_offsets.read().decode())["client.dll"]
        client_data = json.loads(req_client.read().decode())["client.dll"]["classes"]
        
        # Обновляем базовые адреса
        base_conf["dwEntityList"] = offsets_data.get("dwEntityList", base_conf["dwEntityList"])
        base_conf["dwViewMatrix"] = offsets_data.get("dwViewMatrix", base_conf["dwViewMatrix"])
        base_conf["dwLocalPlayerPawn"] = offsets_data.get("dwLocalPlayerPawn", base_conf["dwLocalPlayerPawn"])
        
        # Обновляем смещения классов
        fields = client_data.get("C_BaseEntity", {}).get("fields", {})
        if "m_iHealth" in fields: base_conf["m_iHealth"] = fields["m_iHealth"]
        
        pawn_fields = client_data.get("C_BasePlayerPawn", {}).get("fields", {})
        if "m_vOldOrigin" in pawn_fields: base_conf["m_vOldOrigin"] = pawn_fields["m_vOldOrigin"]
        if "m_iTeamNum" in pawn_fields: base_conf["m_iTeamNum"] = pawn_fields["m_iTeamNum"]
        
        controller_fields = client_data.get("CCSPlayerController", {}).get("fields", {})
        if "m_hPlayerPawn" in controller_fields: base_conf["m_hPlayerPawn"] = controller_fields["m_hPlayerPawn"]
        
        print("[SYSTEM] Offsets successfully synchronized with live servers.")
    except Exception as e:
        print(f"[WARNING] Cloud sync failed ({e}). Using hardcoded fallbacks.")
        
    return base_conf

def world_to_screen(pos, matrix, width, height):
    w = matrix[12] * pos[0] + matrix[13] * pos[1] + matrix[14] * pos[2] + matrix[15]
    if w < 0.01: return None
    
    x = matrix[0] * pos[0] + matrix[1] * pos[1] + matrix[2] * pos[2] + matrix[3]
    y = matrix[4] * pos[0] + matrix[5] * pos[1] + matrix[6] * pos[2] + matrix[7]
    
    screen_x = (width / 2) + (x / w) * (width / 2)
    screen_y = (height / 2) - (y / w) * (height / 2)
    return screen_x, screen_y

def init_overlay():
    if not glfw.init(): return None
    
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)

    screen_w = win32api.GetSystemMetrics(0)
    screen_h = win32api.GetSystemMetrics(1)
    if screen_w == 0 or screen_h == 0: screen_w, screen_h = 1920, 1080

    window = glfw.create_window(screen_w, screen_h, "CS2_OVERLAY_UM", None, None)
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
    # Инициализируем оффсеты из сети
    conf = fetch_live_offsets()
    pm = pymem.Pymem()
    client_dll = None
    
    window, renderer, hwnd, screen_w, screen_h = init_overlay()
    if not window: return

    # Использование флага стандартного доступа уровня пользователя
    PROCESS_ALL_ACCESS = 0x001F0FFF
    PROCESS_VM_READ = 0x0010
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000 # Позволяет видеть процесс без UAC прав
    
    last_topmost_check = time.time()
    
    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()
        
        if time.time() - last_topmost_check > 0.8:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            last_topmost_check = time.time()

        imgui.new_frame()
        imgui.set_next_window_size(float(screen_w), float(screen_h))
        imgui.set_next_window_position(0.0, 0.0)
        imgui.begin("HUD_LAYER", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        draw_list = imgui.get_window_draw_list()
        draw_list.add_text(15, 15, imgui.get_color_u32_rgba(0.0, 1.0, 0.0, 1.0), "STATE: ENGINE_ACTIVE")

        if not client_dll:
            draw_list.add_text(15, 32, imgui.get_color_u32_rgba(1.0, 0.8, 0.0, 1.0), "LINK: Scanning tasks for cs2.exe...")
            for proc in pymem.process.list_processes():
                if "cs2.exe" in str(proc.szExeFile).lower():
                    pid = proc.th32ProcessID
                    # Пробуем открыть сначала в стандартном User-Mode, если игра не в режиме Админа
                    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                    if handle:
                        pm.process_id = pid
                        pm.process_handle = handle
                        try:
                            client_dll = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
                        except: pass
        else:
            draw_list.add_text(15, 32, imgui.get_color_u32_rgba(0.0, 0.8, 1.0, 1.0), "LINK: Connected (User-Mode Bypass)")
            
            targets_count = 0
            try:
                matrix_bytes = pm.read_bytes(client_dll + conf["dwViewMatrix"], 64)
                view_matrix = list(struct.unpack('16f', matrix_bytes))
                entity_list = pm.read_longlong(client_dll + conf["dwEntityList"])
                
                local_team = -1
                try:
                    local_pawn = pm.read_longlong(client_dll + conf["dwLocalPlayerPawn"])
                    if local_pawn: local_team = pm.read_int(local_pawn + conf["m_iTeamNum"])
                except: local_pawn = 0

                if entity_list:
                    for i in range(1, 64): # Сужение пула сканирования до 64 слотов для экономии CPU в User-Mode
                        try:
                            list_entry = pm.read_longlong(entity_list + 0x8 * ((i & 0x7FFF) >> 9) + 0x10)
                            if not list_entry: continue
                            
                            controller = pm.read_longlong(list_entry + 0x78 * (i & 0x1FF))
                            if not controller: continue
                            
                            pawn_handle = pm.read_uint(controller + conf["m_hPlayerPawn"])
                            if not pawn_handle: continue

                            list_entry_pawn = pm.read_longlong(entity_list + 0x8 * ((pawn_handle & 0x7FFF) >> 9) + 0x10)
                            if not list_entry_pawn: continue
                            
                            pawn_ptr = pm.read_longlong(list_entry_pawn + 0x78 * (pawn_handle & 0x1FF))
                            if not pawn_ptr or pawn_ptr == local_pawn: continue

                            health = pm.read_int(pawn_ptr + conf["m_iHealth"])
                            if health <= 0 or health > 100: continue
                            
                            team = pm.read_int(pawn_ptr + conf["m_iTeamNum"])
                            coords = pm.read_bytes(pawn_ptr + conf["m_vOldOrigin"], 12)
                            x, y, z = struct.unpack('3f', coords)

                            screen_pos = world_to_screen([x, y, z], view_matrix, screen_w, screen_h)
                            head_pos = world_to_screen([x, y, z + 65.0], view_matrix, screen_w, screen_h) # 65.0 оптимизировано под Z-высоту моделей

                            if screen_pos and head_pos:
                                targets_count += 1
                                sc_x, sc_y = screen_pos
                                _, h_y = head_pos
                                
                                box_h = max(4.0, sc_y - h_y)
                                box_w = box_h / 1.8
                                
                                color = imgui.get_color_u32_rgba(0.1, 0.6, 1.0, 1.0) if team == local_team else imgui.get_color_u32_rgba(1.0, 0.1, 0.1, 1.0)
                                draw_list.add_rect(sc_x - box_w/2, h_y, sc_x + box_w/2, sc_y, color, 0.0, 0, 1.5)

                                hp_p = health / 100.0
                                hp_color = imgui.get_color_u32_rgba(1.0 - hp_p, hp_p, 0.0, 1.0)
                                hp_h = box_h * hp_p
                                
                                draw_list.add_rect_filled(sc_x - box_w/2 - 6, h_y, sc_x - box_w/2 - 2, sc_y, imgui.get_color_u32_rgba(0.0, 0.0, 0.0, 0.5))
                                draw_list.add_rect_filled(sc_x - box_w/2 - 5, sc_y - hp_h, sc_x - box_w/2 - 3, sc_y, hp_color)
                        except: continue
            except: client_dll = None
                
            draw_list.add_text(15, 49, imgui.get_color_u32_rgba(1.0, 1.0, 1.0, 1.0), f"TARGETS VISIBLE: {targets_count}")

        imgui.end()
        
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        renderer.render(imgui.get_draw_data())
        glfw.swap_buffers(window)

    renderer.shutdown()
    glfw.terminate()

if __name__ == "__main__":
    main()
