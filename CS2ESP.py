import os
import sys

# ФИКС PYOPENGL: Принудительно отключаем поиск numpy до импорта OpenGL
os.environ['PYOPENGL_PLATFORM'] = 'egl' 
import OpenGL
OpenGL.ERROR_CHECKING = False
OpenGL.ERROR_LOGGING = False

import json
import time
import pymem
import pymem.exception
import glfw
import OpenGL.GL as gl
import imgui
from imgui.integrations.glfw import GlfwRenderer
import ctypes
import struct

# Системные библиотеки Windows
import win32api
import win32gui
import win32con

# ==========================================
# 1. ЗАГРУЗКА ОФФСЕТОВ ИЗ ОТДЕЛЬНОЙ ПАПКИ
# ==========================================
def load_offsets():
    offsets_dict = {
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

    print(f"[INFO] Поиск папки с оффсетами в: {os.path.join(root_dir, 'offsets')}")

    if os.path.exists(offsets_path) and os.path.exists(client_dll_path):
        try:
            with open(offsets_path, "r") as f:
                raw_offsets = json.load(f)["client.dll"]
            with open(client_dll_path, "r") as f:
                raw_classes = json.load(f)["client.dll"]["classes"]

            offsets_dict["dwEntityList"] = raw_offsets.get("dwEntityList", offsets_dict["dwEntityList"])
            offsets_dict["dwViewMatrix"] = raw_offsets.get("dwViewMatrix", offsets_dict["dwViewMatrix"])
            offsets_dict["dwLocalPlayerPawn"] = raw_offsets.get("dwLocalPlayerPawn", offsets_dict["dwLocalPlayerPawn"])

            def parse_field(field_data):
                if isinstance(field_data, dict):
                    return field_data.get("value", field_data.get("offset", 0))
                return field_data

            for class_name, class_body in raw_classes.items():
                fields = class_body.get("fields", {})
                if "m_iHealth" in fields:
                    offsets_dict["m_iHealth"] = parse_field(fields["m_iHealth"])
                if "m_hPlayerPawn" in fields:
                    offsets_dict["m_hPlayerPawn"] = parse_field(fields["m_hPlayerPawn"])
                if "m_vOldOrigin" in fields:
                    offsets_dict["m_vOldOrigin"] = parse_field(fields["m_vOldOrigin"])
                if "m_iTeamNum" in fields:
                    offsets_dict["m_iTeamNum"] = parse_field(fields["m_iTeamNum"])
            
            print("[SUCCESS] Оффсеты успешно сопоставлены из внешней папки!")
        except Exception as e:
            print(f"[WARN] Ошибка парсинга внешних JSON: {e}. Используются базовые адреса.")
    else:
        print("[WARN] Внешняя папка 'offsets' не найдена рядом с файлом! Используются базовые адреса.")
        
    return offsets_dict

# ==========================================
# 2. ИСПРАВЛЕННАЯ МАТЕМАТИКА W2S (ПИКСЕЛИ)
# ==========================================
def world_to_screen(pos, matrix, width, height):
    # Рассчитываем глубину W
    w = matrix[12] * pos[0] + matrix[13] * pos[1] + matrix[14] * pos[2] + matrix[15]
    if w < 0.01:
        return None
    
    # Рассчитываем нормализованные координаты X и Y
    x = matrix[0] * pos[0] + matrix[1] * pos[1] + matrix[2] * pos[2] + matrix[3]
    y = matrix[4] * pos[0] + matrix[5] * pos[1] + matrix[6] * pos[2] + matrix[7]
    
    # Переводим строго в абсолютные пиксели монитора игрока
    screen_x = (width / 2) + (x / w) * (width / 2)
    screen_y = (height / 2) - (y / w) * (height / 2)
    
    return screen_x, screen_y

# ==========================================
# 3. НАСТРОЙКА ГРАФИЧЕСКОГО ОКНА ОВЕРЛЕЯ
# ==========================================
def init_overlay():
    if not glfw.init():
        return None
    
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)

    screen_w = int(win32api.GetSystemMetrics(0))
    screen_h = int(win32api.GetSystemMetrics(1))
    
    if screen_w == 0 or screen_h == 0:
        screen_w, screen_h = 1920, 1080

    window = glfw.create_window(screen_w, screen_h, "CS2_PRO_OVERLAY", None, None)
    if not window:
        glfw.terminate()
        return None
        
    glfw.make_context_current(window)
    glfw.swap_interval(1)
    
    hwnd = glfw.get_win32_window(window)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, 
                           win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)

    imgui.create_context()
    renderer = GlfwRenderer(window)
    return window, renderer, screen_w, screen_h

# ==========================================
# 4. ДВИЖОК ЧТЕНИЯ ПАМЯТИ И РЕНДЕР
# ==========================================
def main():
    conf = load_offsets()
    print("[INFO] Ожидание запуска CS2 (Безопасный режим без прав администратора)...")
    
    pm = pymem.Pymem()
    client_dll = None
    
    while True:
        try:
            pid = None
            for proc in pymem.process.list_processes():
                try:
                    exe_name = proc.szExeFile.decode('utf-8', errors='ignore').lower()
                except Exception:
                    exe_name = str(proc.szExeFile).lower()
                
                if "cs2.exe" in exe_name:
                    pid = proc.th32ProcessID
                    break
            
            if pid:
                PROCESS_VM_READ = 0x0010
                PROCESS_QUERY_INFORMATION = 0x0400
                
                handle = ctypes.windll.kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
                
                if handle:
                    pm.process_id = pid
                    pm.process_handle = handle
                    client_dll = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
                    print("[SUCCESS] Подключение к памяти без прав Администратора выполнено успешно!")
                    break
            time.sleep(1)
        except Exception:
            time.sleep(1)

    window, renderer, screen_w, screen_h = init_overlay()
    if not window:
        return

    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()
        
        imgui.new_frame()
        imgui.set_next_window_size(float(screen_w), float(screen_h))
        imgui.set_next_window_position(0.0, 0.0)
        imgui.begin("OverlayWindow", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        draw_list = imgui.get_window_draw_list()

        try:
            # Читаем матрицу единым пулом (64 байта)
            matrix_bytes = pm.read_bytes(client_dll + conf["dwViewMatrix"], 64)
            view_matrix = list(struct.unpack('16f', matrix_bytes))
            
            entity_list = pm.read_longlong(client_dll + conf["dwEntityList"])
            
            local_team = -1
            try:
                local_player_pawn = pm.read_longlong(client_dll + conf["dwLocalPlayerPawn"])
                if local_player_pawn and local_player_pawn != 0:
                    local_team = pm.read_int(local_player_pawn + conf["m_iTeamNum"])
            except Exception:
                local_player_pawn = 0

            if entity_list and entity_list != 0:
                for i in range(1, 64):
                    try:
                        chunk_idx = (i & 0x7FFF) >> 9
                        inside_idx = i & 0x1FF

                        list_entry = pm.read_longlong(entity_list + 0x8 * chunk_idx + 0x10)
                        if not list_entry or list_entry == 0:
                            continue

                        player_controller = pm.read_longlong(list_entry + 0x78 * inside_idx)
                        if not player_controller or player_controller == 0:
                            continue

                        pawn_handle = pm.read_uint(player_controller + conf["m_hPlayerPawn"])
                        if not pawn_handle or pawn_handle == 0:
                            continue

                        pawn_chunk_idx = (pawn_handle & 0x7FFF) >> 9
                        pawn_inside_idx = pawn_handle & 0x1FF

                        list_entry_pawn = pm.read_longlong(entity_list + 0x8 * pawn_chunk_idx + 0x10)
                        if not list_entry_pawn or list_entry_pawn == 0:
                            continue

                        pawn_ptr = pm.read_longlong(list_entry_pawn + 0x78 * pawn_inside_idx)
                        if not pawn_ptr or pawn_ptr == 0 or pawn_ptr == local_player_pawn:
                            continue

                        health = pm.read_int(pawn_ptr + conf["m_iHealth"])
                        if health <= 0 or health > 100:
                            continue

                        team = pm.read_int(pawn_ptr + conf["m_iTeamNum"])

                        # АТОМАРНОЕ ЧТЕНИЕ КООРДИНАТ: Читаем Vector3 (12 байт) за раз, чтобы избежать сдвигов
                        coord_bytes = pm.read_bytes(pawn_ptr + conf["m_vOldOrigin"], 12)
                        pos_x, pos_y, pos_z = struct.unpack('3f', coord_bytes)

                        # Передаем размеры экрана в функцию перевода координат
                        screen_pos = world_to_screen([pos_x, pos_y, pos_z], view_matrix, screen_w, screen_h)
                        
                        if screen_pos:
                            sc_x, sc_y = screen_pos
                            
                            head_pos = world_to_screen([pos_x, pos_y, pos_z + 72.0], view_matrix, screen_w, screen_h)
                            if head_pos:
                                h_y = head_pos[1]
                                box_height = max(5.0, sc_y - h_y)
                                box_width = box_height / 1.8
                                
                                if team == local_team and local_team != -1:
                                    color = imgui.get_color_u32_rgba(0.2, 0.6, 1.0, 1.0) # Синий (Союзники)
                                else:
                                    color = imgui.get_color_u32_rgba(1.0, 0.2, 0.2, 1.0) # Красный (Враги/Боты)
                                
                                # Прямая отрисовка пиксельных координат
                                draw_list.add_rect(
                                    sc_x - (box_width / 2), 
                                    h_y, 
                                    sc_x + (box_width / 2), 
                                    sc_y, 
                                    color, 
                                    0.0, 
                                    0, 
                                    1.5
                                )
                                
                                draw_list.add_text(sc_x - (box_width / 2), h_y - 15, color, f"{health} HP")

                    except pymem.exception.MemoryReadError:
                        continue
        except pymem.exception.MemoryReadError:
            pass
        except Exception:
            pass

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
