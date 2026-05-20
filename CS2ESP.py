import os
import sys
import json
import time
import ctypes
import struct
import warnings

# Гасим предупреждения
warnings.filterwarnings("ignore", category=UserWarning, module='OpenGL')

# === КРИТИЧЕСКИЕ ФИКСЫ WINDOWS ===
# 1. Отключаем масштабирование экрана (DPI), чтобы пиксели оверлея = пикселям игры
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

# 2. Фикс PyOpenGL для PyInstaller
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

# Структура для прозрачности
class MARGINS(ctypes.Structure):
    _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

# ==========================================
# 1. УМНЫЙ ЗАГРУЗЧИК ОФФСЕТОВ
# ==========================================
def load_offsets():
    # Актуальные (надежные) базовые оффсеты на момент последних апдейтов
    offsets = {
        "dwEntityList": 0x18C2DB8, 
        "dwViewMatrix": 0x19242A0, 
        "dwLocalPlayerPawn": 0x1823A08,
        "m_iHealth": 0x32C, 
        "m_hPlayerPawn": 0x7BC, 
        "m_vOldOrigin": 0x1274, 
        "m_iTeamNum": 0x3BF
    }

    if getattr(sys, 'frozen', False):
        root_dir = os.path.dirname(sys.executable)
    else:
        root_dir = os.path.dirname(os.path.abspath(__file__))

    offsets_path = os.path.join(root_dir, "offsets", "offsets.json")
    client_dll_path = os.path.join(root_dir, "offsets", "client_dll.json")

    if os.path.exists(offsets_path) and os.path.exists(client_dll_path):
        try:
            with open(offsets_path, "r") as f:
                raw_offsets = json.load(f)["client.dll"]
            with open(client_dll_path, "r") as f:
                raw_classes = json.load(f)["client.dll"]["classes"]

            offsets["dwEntityList"] = raw_offsets.get("dwEntityList", offsets["dwEntityList"])
            offsets["dwViewMatrix"] = raw_offsets.get("dwViewMatrix", offsets["dwViewMatrix"])
            offsets["dwLocalPlayerPawn"] = raw_offsets.get("dwLocalPlayerPawn", offsets["dwLocalPlayerPawn"])

            def parse_val(data):
                return data.get("value", data.get("offset", 0)) if isinstance(data, dict) else data

            # Сканируем классы
            for cls in ["C_BaseEntity", "C_BasePlayerPawn", "CCSPlayerController"]:
                if cls in raw_classes:
                    fields = raw_classes[cls].get("fields", {})
                    if "m_iHealth" in fields: offsets["m_iHealth"] = parse_val(fields["m_iHealth"])
                    if "m_hPlayerPawn" in fields: offsets["m_hPlayerPawn"] = parse_val(fields["m_hPlayerPawn"])
                    if "m_vOldOrigin" in fields: offsets["m_vOldOrigin"] = parse_val(fields["m_vOldOrigin"])
                    if "m_iTeamNum" in fields: offsets["m_iTeamNum"] = parse_val(fields["m_iTeamNum"])
        except Exception:
            pass
    return offsets

# ==========================================
# 2. МАТЕМАТИКА W2S (3D в 2D)
# ==========================================
def world_to_screen(pos, matrix, width, height):
    w = matrix[12] * pos[0] + matrix[13] * pos[1] + matrix[14] * pos[2] + matrix[15]
    if w < 0.01:
        return None # Объект за спиной
    
    x = matrix[0] * pos[0] + matrix[1] * pos[1] + matrix[2] * pos[2] + matrix[3]
    y = matrix[4] * pos[0] + matrix[5] * pos[1] + matrix[6] * pos[2] + matrix[7]
    
    screen_x = (width / 2) + (x / w) * (width / 2)
    screen_y = (height / 2) - (y / w) * (height / 2)
    return screen_x, screen_y

# ==========================================
# 3. АГРЕССИВНЫЙ ОВЕРЛЕЙ
# ==========================================
def init_overlay():
    if not glfw.init(): return None
    
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)

    screen_w = win32api.GetSystemMetrics(0)
    screen_h = win32api.GetSystemMetrics(1)

    window = glfw.create_window(screen_w, screen_h, "CS2_GOD_ESP", None, None)
    if not window:
        glfw.terminate()
        return None
        
    glfw.make_context_current(window)
    glfw.swap_interval(1) # VSync (убирает мерцание)
    
    hwnd = glfw.get_win32_window(window)
    
    # Делаем окно полностью клик-тру и прозрачным
    ex_style = win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

    # Агрессивно выталкиваем поверх всех окон
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)

    # Фикс DWM для прозрачности
    try:
        dwmapi = ctypes.WinDLL('dwmapi')
        margins = MARGINS(-1, -1, -1, -1)
        dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
    except:
        pass

    imgui.create_context()
    renderer = GlfwRenderer(window)
    return window, renderer, hwnd, screen_w, screen_h

# ==========================================
# 4. ДВИЖОК
# ==========================================
def main():
    conf = load_offsets()
    pm = pymem.Pymem()
    client_dll = None
    
    window, renderer, hwnd, screen_w, screen_h = init_overlay()
    if not window: return

    # Системные флаги для прав без Админа (только чтение)
    PROCESS_VM_READ = 0x0010
    PROCESS_QUERY_INFORMATION = 0x0400

    last_topmost_check = time.time()
    
    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()
        
        # Раз в секунду принудительно выталкиваем оверлей наверх
        if time.time() - last_topmost_check > 1.0:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            last_topmost_check = time.time()

        imgui.new_frame()
        imgui.set_next_window_size(float(screen_w), float(screen_h))
        imgui.set_next_window_position(0.0, 0.0)
        imgui.begin("ESP_LAYER", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        draw_list = imgui.get_window_draw_list()
        
        # --- БЛОК ИНДИКАЦИИ (ОСД) ---
        # Если ты видишь этот текст в игре — значит графическая часть работает 100%
        draw_list.add_text(10, 10, imgui.get_color_u32_rgba(0, 1, 0, 1), "[+] CS2 ESP STATUS: ACTIVE")

        # Пытаемся зацепиться за игру без админ прав
        if not client_dll:
            draw_list.add_text(10, 25, imgui.get_color_u32_rgba(1, 1, 0, 1), "[-] Ожидание CS2.exe...")
            for proc in pymem.process.list_processes():
                if "cs2.exe" in str(proc.szExeFile).lower():
                    pid = proc.th32ProcessID
                    handle = ctypes.windll.kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
                    if handle:
                        pm.process_id = pid
                        pm.process_handle = handle
                        try:
                            client_dll = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
                        except:
                            pass
        else:
            # Чтение памяти и ВХ
            draw_list.add_text(10, 25, imgui.get_color_u32_rgba(0, 1, 1, 1), f"[+] Память читается (Без Админа)")
            players_found = 0

            try:
                matrix_bytes = pm.read_bytes(client_dll + conf["dwViewMatrix"], 64)
                view_matrix = list(struct.unpack('16f', matrix_bytes))
                entity_list = pm.read_longlong(client_dll + conf["dwEntityList"])
                
                local_team = -1
                try:
                    local_pawn = pm.read_longlong(client_dll + conf["dwLocalPlayerPawn"])
                    if local_pawn: local_team = pm.read_int(local_pawn + conf["m_iTeamNum"])
                except:
                    local_pawn = 0

                if entity_list:
                    for i in range(1, 64):
                        try:
                            list_entry = pm.read_longlong(entity_list + 0x8 * ((i & 0x7FFF) >> 9) + 0x10)
                            if not list_entry: continue
                            controller = pm.read_longlong(list_entry + 0x78 * (i & 0x1FF))
                            if not controller: continue
                            pawn_handle = pm.read_uint(controller + conf["m_hPlayerPawn"])
                            if not pawn_handle: continue

                            list_entry_pawn = pm.read_longlong(entity_list + 0x8 * ((pawn_handle & 0x7FFF) >> 9) + 0x10)
                            pawn_ptr = pm.read_longlong(list_entry_pawn + 0x78 * (pawn_handle & 0x1FF))
                            if not pawn_ptr or pawn_ptr == local_pawn: continue

                            health = pm.read_int(pawn_ptr + conf["m_iHealth"])
                            if health <= 0 or health > 100: continue
                            team = pm.read_int(pawn_ptr + conf["m_iTeamNum"])

                            players_found += 1

                            coords = pm.read_bytes(pawn_ptr + conf["m_vOldOrigin"], 12)
                            x, y, z = struct.unpack('3f', coords)

                            screen_pos = world_to_screen([x, y, z], view_matrix, screen_w, screen_h)
                            head_pos = world_to_screen([x, y, z + 65.0], view_matrix, screen_w, screen_h)

                            if screen_pos and head_pos:
                                sc_x, sc_y = screen_pos
                                _, h_y = head_pos
                                
                                box_h = max(5.0, sc_y - h_y)
                                box_w = box_h / 2.0
                                
                                # Цвета: Синий свои, Красный враги
                                color = imgui.get_color_u32_rgba(0, 0.5, 1, 1) if team == local_team else imgui.get_color_u32_rgba(1, 0, 0, 1)

                                # Отрисовка Бокса
                                draw_list.add_rect(sc_x - box_w/2, h_y, sc_x + box_w/2, sc_y, color, 0, 0, 1.5)

                                # Качественная полоска здоровья (Healthbar)
                                hp_perc = health / 100.0
                                hp_color = imgui.get_color_u32_rgba(1-hp_perc, hp_perc, 0, 1)
                                hp_h = box_h * hp_perc
                                
                                # Фон ХП
                                draw_list.add_rect_filled(sc_x - box_w/2 - 6, h_y, sc_x - box_w/2 - 2, sc_y, imgui.get_color_u32_rgba(0,0,0,0.6))
                                # Сама ХП
                                draw_list.add_rect_filled(sc_x - box_w/2 - 5, sc_y - hp_h, sc_x - box_w/2 - 3, sc_y, hp_color)
                        except Exception:
                            continue
                draw_list.add_text(10, 40, imgui.get_color_u32_rgba(1, 1, 1, 1), f"[*] Игроков в зоне видимости: {players_found}")
            except Exception:
                client_dll = None

        imgui.end()
        
        gl.glClearColor(0, 0, 0, 0) # КРИТИЧНО ДЛЯ ПРОЗРАЧНОСТИ
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        renderer.render(imgui.get_draw_data())
        glfw.swap_buffers(window)

    renderer.shutdown()
    glfw.terminate()

if __name__ == "__main__":
    main()
