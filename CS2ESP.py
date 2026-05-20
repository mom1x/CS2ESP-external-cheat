import os
import sys
import json
import time
import ctypes
import struct
import warnings

# Отключаем лишние логи движка графики
warnings.filterwarnings("ignore", category=UserWarning, module='OpenGL')

# === СИСТЕМНЫЕ СТАБИЛИЗАТОРЫ WINDOWS ===
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except:
        pass

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

# ==========================================
# УМНЫЙ АДАПТИВНЫЙ ПАРСЕР ОФФСЕТОВ
# ==========================================
def load_offsets():
    # Жесткие базовые оффсеты на случай отсутствия папки
    conf = {
        "dwEntityList": 0x18C2DB8, 
        "dwViewMatrix": 0x19242A0, 
        "dwLocalPlayerPawn": 0x1823A08,
        "m_iHealth": 0x32C, 
        "m_hPlayerPawn": 0x7BC, 
        "m_vOldOrigin": 0x1274, 
        "m_iTeamNum": 0x3BF
    }

    # Проверяем все возможные пути нахождения папки offsets
    possible_roots = [
        os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
        os.path.dirname(os.path.abspath(__file__))
    ]

    for root in possible_roots:
        offsets_path = os.path.join(root, "offsets", "offsets.json")
        client_dll_path = os.path.join(root, "offsets", "client_dll.json")

        if os.path.exists(offsets_path) and os.path.exists(client_dll_path):
            try:
                with open(offsets_path, "r") as f:
                    raw_offsets = json.load(f)["client.dll"]
                with open(client_dll_path, "r") as f:
                    raw_classes = json.load(f)["client.dll"]["classes"]

                conf["dwEntityList"] = raw_offsets.get("dwEntityList", conf["dwEntityList"])
                conf["dwViewMatrix"] = raw_offsets.get("dwViewMatrix", conf["dwViewMatrix"])
                conf["dwLocalPlayerPawn"] = raw_offsets.get("dwLocalPlayerPawn", conf["dwLocalPlayerPawn"])

                def parse_val(d):
                    return d.get("value", d.get("offset", 0)) if isinstance(d, dict) else d

                # Расширенный список классов для детекта обновлений CS2
                for cls in ["C_BaseEntity", "C_BasePlayerPawn", "CCSPlayerController", "C_CSPlayerPawnBase", "C_BasePlayerController"]:
                    if cls in raw_classes:
                        fields = raw_classes[cls].get("fields", {})
                        if "m_iHealth" in fields: conf["m_iHealth"] = parse_val(fields["m_iHealth"])
                        if "m_hPlayerPawn" in fields: conf["m_hPlayerPawn"] = parse_val(fields["m_hPlayerPawn"])
                        if "m_vOldOrigin" in fields: conf["m_vOldOrigin"] = parse_val(fields["m_vOldOrigin"])
                        if "m_iTeamNum" in fields: conf["m_iTeamNum"] = parse_val(fields["m_iTeamNum"])
                break
            except:
                pass
    return conf

# ==========================================
# МАТЕМАТИКА ПРОЕКЦИИ (W2S)
# ==========================================
def world_to_screen(pos, matrix, width, height):
    w = matrix[12] * pos[0] + matrix[13] * pos[1] + matrix[14] * pos[2] + matrix[15]
    if w < 0.01: return None
    
    x = matrix[0] * pos[0] + matrix[1] * pos[1] + matrix[2] * pos[2] + matrix[3]
    y = matrix[4] * pos[0] + matrix[5] * pos[1] + matrix[6] * pos[2] + matrix[7]
    
    screen_x = (width / 2) + (x / w) * (width / 2)
    screen_y = (height / 2) - (y / w) * (height / 2)
    return screen_x, screen_y

# ==========================================
# ИНИЦИАЛИЗАЦИЯ НЕВИДИМОГО ОКНА
# ==========================================
def init_overlay():
    if not glfw.init(): return None
    
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)

    screen_w = win32api.GetSystemMetrics(0)
    screen_h = win32api.GetSystemMetrics(1)
    if screen_w == 0 or screen_h == 0: screen_w, screen_h = 1920, 1080

    window = glfw.create_window(screen_w, screen_h, "CS2_ENGINE_OVERLAY", None, None)
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
    except:
        pass

    imgui.create_context()
    renderer = GlfwRenderer(window)
    return window, renderer, hwnd, screen_w, screen_h

# ==========================================
# ГЛАВНЫЙ ПОТОК ОБРАБОТКИ
# ==========================================
def main():
    conf = load_offsets()
    pm = pymem.Pymem()
    client_dll = None
    
    window, renderer, hwnd, screen_w, screen_h = init_overlay()
    if not window: return

    # Права доступа уровня обычного пользователя (bypass UAC)
    PROCESS_VM_READ = 0x0010
    PROCESS_QUERY_INFORMATION = 0x0400
    last_topmost_check = time.time()
    
    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()
        
        # Удержание поверх всех окон (защита от перекрытия игрой)
        if time.time() - last_topmost_check > 0.8:
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
            last_topmost_check = time.time()

        imgui.new_frame()
        imgui.set_next_window_size(float(screen_w), float(screen_h))
        imgui.set_next_window_position(0.0, 0.0)
        imgui.begin("HUD_LAYER", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        draw_list = imgui.get_window_draw_list()
        
        # 1. СТАТУС КАНАЛАОТРИСОВКИ (Зеленый)
        draw_list.add_text(15, 15, imgui.get_color_u32_rgba(0.0, 1.0, 0.0, 1.0), "STATE: ENGINE_ACTIVE")

        # Навешиваем хук на память без вызова контроля учетных записей (UAC)
        if not client_dll:
            # 2. ПОИСК ПРОЦЕССА (Желтый/Голубой)
            draw_list.add_text(15, 32, imgui.get_color_u32_rgba(1.0, 0.8, 0.0, 1.0), "LINK: Looking for cs2.exe...")
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
            draw_list.add_text(15, 32, imgui.get_color_u32_rgba(0.0, 0.8, 1.0, 1.0), "LINK: Connected (User-Mode)")
            
            targets_count = 0
            try:
                # Считываем матрицу камеры игрока
                matrix_bytes = pm.read_bytes(client_dll + conf["dwViewMatrix"], 64)
                view_matrix = list(struct.unpack('16f', matrix_bytes))
                
                # Считываем глобальный список сущностей
                entity_list = pm.read_longlong(client_dll + conf["dwEntityList"])
                
                local_team = -1
                try:
                    local_pawn = pm.read_longlong(client_dll + conf["dwLocalPlayerPawn"])
                    if local_pawn: local_team = pm.read_int(local_pawn + conf["m_iTeamNum"])
                except:
                    local_pawn = 0

                if entity_list:
                    # Расширенный цикл до 128 слотов, чтобы железно захватывать всех ботов в любых режимах
                    for i in range(1, 128):
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

                            # Считывание позиции объекта из памяти
                            coords = pm.read_bytes(pawn_ptr + conf["m_vOldOrigin"], 12)
                            x, y, z = struct.unpack('3f', coords)

                            screen_pos = world_to_screen([x, y, z], view_matrix, screen_w, screen_h)
                            head_pos = world_to_screen([x, y, z + 68.0], view_matrix, screen_w, screen_h)

                            if screen_pos and head_pos:
                                targets_count += 1
                                sc_x, sc_y = screen_pos
                                _, h_y = head_pos
                                
                                box_h = max(4.0, sc_y - h_y)
                                box_w = box_h / 1.8
                                
                                # Определение цвета (Синий — тимейты, Красный — противники)
                                color = imgui.get_color_u32_rgba(0.1, 0.6, 1.0, 1.0) if team == local_team else imgui.get_color_u32_rgba(1.0, 0.1, 0.1, 1.0)

                                # Рисуем 2D Бокс игрока
                                draw_list.add_rect(sc_x - box_w/2, h_y, sc_x + box_w/2, sc_y, color, 0.0, 0, 1.5)

                                # Масштабируемый динамический Индикатор Здоровья (Healthbar)
                                hp_p = health / 100.0
                                hp_color = imgui.get_color_u32_rgba(1.0 - hp_p, hp_p, 0.0, 1.0)
                                hp_h = box_h * hp_p
                                
                                # Задняя подложка бара
                                draw_list.add_rect_filled(sc_x - box_w/2 - 6, h_y, sc_x - box_w/2 - 2, sc_y, imgui.get_color_u32_rgba(0.0, 0.0, 0.0, 0.5))
                                # Заполнение цветом здоровья
                                draw_list.add_rect_filled(sc_x - box_w/2 - 5, sc_y - hp_h, sc_x - box_w/2 - 3, sc_y, hp_color)
                        except:
                            continue
            except:
                client_dll = None
                
            # 3. СЧЕТЧИК ЦЕЛЕЙ (Белый)
            draw_list.add_text(15, 49, imgui.get_color_u32_rgba(1.0, 1.0, 1.0, 1.0), f"TARGETS VISIBLE: {targets_count}")

        imgui.end()
        
        # Очистка кадра альфа-нулем для прозрачности DWM Windows
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        renderer.render(imgui.get_draw_data())
        glfw.swap_buffers(window)

    renderer.shutdown()
    glfw.terminate()

if __name__ == "__main__":
    main()
