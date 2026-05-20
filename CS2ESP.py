import os
import sys
import json
import time
import pymem
import pymem.exception
import glfw
import OpenGL.GL as gl
import imgui
from imgui.integrations.glfw import GlfwRenderer

# Системные библиотеки Windows
import win32api
import win32gui
import win32con

# ==========================================
# 1. БУЛЛЕТПРУФ ЗАГРУЗКА ОФФСЕТОВ
# ==========================================
def load_offsets():
    print("[INFO] Загрузка встроенных оффсетов из папки offsets...")
    
    # Резервный хардкод на случай критического сбоя файловой системы
    offsets_dict = {
        "dwEntityList": 0x18C2DB8, 
        "dwViewMatrix": 0x19242A0, 
        "dwLocalPlayerPawn": 0x1823A08,
        "m_iHealth": 0x32C, 
        "m_hPlayerPawn": 0x7BC, 
        "m_vOldOrigin": 0x1274, 
        "m_iTeamNum": 0x3BF
    }

    try:
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        offsets_path = os.path.join(base_path, "offsets", "offsets.json")
        client_dll_path = os.path.join(base_path, "offsets", "client_dll.json")

        if os.path.exists(offsets_path) and os.path.exists(client_dll_path):
            with open(offsets_path, "r") as f:
                raw_offsets = json.load(f)["client.dll"]
            with open(client_dll_path, "r") as f:
                raw_classes = json.load(f)["client.dll"]["classes"]

            # Глобальные смещения (обычно всегда прямые числа)
            offsets_dict["dwEntityList"] = raw_offsets.get("dwEntityList", offsets_dict["dwEntityList"])
            offsets_dict["dwViewMatrix"] = raw_offsets.get("dwViewMatrix", offsets_dict["dwViewMatrix"])
            offsets_dict["dwLocalPlayerPawn"] = raw_offsets.get("dwLocalPlayerPawn", offsets_dict["dwLocalPlayerPawn"])

            # Внутренняя функция для безопасного извлечения смещения из любого формата JSON
            def parse_field(field_data):
                if isinstance(field_data, dict):
                    return field_data.get("value", field_data.get("offset", 0))
                return field_data

            # Сканируем классы на наличие нужных нам переменных
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
            
            print("[SUCCESS] Оффсеты успешно сопоставлены из актуального JSON!")
    except Exception as e:
        print(f"[WARN] Не удалось разобрать JSON (работает резервный кэш): {e}")
        
    return offsets_dict

# ==========================================
# 2. МАТЕМАТИКА ПРОЕКЦИИ (WORLD TO SCREEN)
# ==========================================
def world_to_screen(pos, matrix):
    w = matrix[12] * pos[0] + matrix[13] * pos[1] + matrix[14] * pos[2] + matrix[15]
    if w < 0.01:
        return None
    
    x = matrix[0] * pos[0] + matrix[1] * pos[1] + matrix[2] * pos[2] + matrix[3]
    y = matrix[4] * pos[0] + matrix[5] * pos[1] + matrix[6] * pos[2] + matrix[7]
    
    screen_x = (x / w) + 1.0
    screen_y = 1.0 - (y / w)
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

    # Запрашиваем разрешение экрана напрямую у Windows
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
    
    # Применяем прозрачность и игнорирование кликов на уровне Windows Styles
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
    print("[INFO] Ожидание запуска CS2...")
    
    pm = None
    client_dll = None
    
    while True:
        try:
            pm = pymem.Pymem("cs2.exe")
            client_dll = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
            print("[SUCCESS] Успешное подключение к памяти CS2!")
            break
        except pymem.exception.ProcessNotFound:
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
            # Считываем 16 значений матрицы камеры
            view_matrix = [pm.read_float(client_dll + conf["dwViewMatrix"] + (m_idx * 4)) for m_idx in range(16)]
            entity_list = pm.read_longlong(client_dll + conf["dwEntityList"])
            
            # Безопасное определение нашей команды
            local_team = -1
            try:
                local_player_pawn = pm.read_longlong(client_dll + conf["dwLocalPlayerPawn"])
                if local_player_pawn and local_player_pawn != 0:
                    local_team = pm.read_int(local_player_pawn + conf["m_iTeamNum"])
            except Exception:
                local_player_pawn = 0

            if entity_list and entity_list != 0:
                # Проходим по индексам сущностей (игроки и боты занимают первые 64 слота)
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

                        # Переходим к физическому объекту игрока (Pawn)
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

                        # Считываем позицию ног (X, Y, Z)
                        pos_x = pm.read_float(pawn_ptr + conf["m_vOldOrigin"])
                        pos_y = pm.read_float(pawn_ptr + conf["m_vOldOrigin"] + 4)
                        pos_z = pm.read_float(pawn_ptr + conf["m_vOldOrigin"] + 8)

                        screen_pos = world_to_screen([pos_x, pos_y, pos_z], view_matrix)
                        
                        if screen_pos:
                            sc_x = screen_pos[0] * (screen_w / 2)
                            sc_y = screen_pos[1] * (screen_h / 2)
                            
                            # Находим позицию головы (рост модели игрока в CS2 равен ~72 единицам)
                            head_pos = world_to_screen([pos_x, pos_y, pos_z + 72.0], view_matrix)
                            if head_pos:
                                h_y = head_pos[1] * (screen_h / 2)
                                box_height = max(5.0, sc_y - h_y)
                                box_width = box_height / 1.8
                                
                                # Распределение цветов
                                if team == local_team and local_team != -1:
                                    color = imgui.get_color_u32_rgba(0.2, 0.6, 1.0, 1.0) # Союзники - Синие
                                else:
                                    color = imgui.get_color_u32_rgba(1.0, 0.2, 0.2, 1.0) # Враги/Боты - Красные
                                
                                # Отрисовка прямоугольника (Строго позиционные аргументы Cython)
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
                                
                                # Отрисовка текста здоровья
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
