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

# Импортируем системные библиотеки Windows для надежного получения разрешения экрана
import win32api
import win32gui
import win32con

# ==========================================
# 1. ЗАГРУЗКА ОФФСЕТОВ ИЗ JSON
# ==========================================
def load_offsets():
    print("[INFO] Загрузка встроенных оффсетов из папки offsets...")
    try:
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        offsets_path = os.path.join(base_path, "offsets", "offsets.json")
        client_dll_path = os.path.join(base_path, "offsets", "client_dll.json")

        with open(offsets_path, "r") as f:
            offsets = json.load(f)["client.dll"]
        with open(client_dll_path, "r") as f:
            client_data = json.load(f)["client.dll"]["classes"]

        return {
            "dwEntityList": offsets["dwEntityList"],
            "dwViewMatrix": offsets["dwViewMatrix"],
            "dwLocalPlayerPawn": offsets["dwLocalPlayerPawn"],
            "m_iHealth": client_data.get("C_BaseEntity", {}).get("fields", {}).get("m_iHealth", 0x32C),
            "m_hPlayerPawn": client_data.get("CCSPlayerController", {}).get("fields", {}).get("m_hPlayerPawn", 0x7BC),
            "m_vOldOrigin": client_data.get("C_BasePlayerPawn", {}).get("fields", {}).get("m_vOldOrigin", 0x1274),
            "m_iTeamNum": client_data.get("C_BaseEntity", {}).get("fields", {}).get("m_iTeamNum", 0x3bf)
        }
    except Exception as e:
        print(f"[ERROR] Не удалось загрузить JSON файлы: {e}")
        print("[INFO] Включаем резервные встроенные оффсеты...")
        return {
            "dwEntityList": 0x18C2DB8, "dwViewMatrix": 0x19242A0, "dwLocalPlayerPawn": 0x1823A08,
            "m_iHealth": 0x32C, "m_hPlayerPawn": 0x7BC, "m_vOldOrigin": 0x1274, "m_iTeamNum": 0x3bf
        }

# ==========================================
# 2. МАТЕМАТИКА (WORLD TO SCREEN)
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
# 3. ИНИЦИАЛИЗАЦИЯ GLFW И ЗАЩИЩЕННЫЙ ОВЕРЛЕЙ
# ==========================================
def init_overlay():
    if not glfw.init():
        return None
    
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE)

    # Жестко и надежно запрашиваем разрешение экрана у Windows в формате INT
    screen_w = int(win32api.GetSystemMetrics(0))
    screen_h = int(win32api.GetSystemMetrics(1))
    
    # Подстраховка на случай непредвиденных нулевых значений
    if screen_w == 0 or screen_h == 0:
        screen_w, screen_h = 1920, 1080

    # Передаем строго приведенные к int типы данных, чтобы ctypes не ругался
    window = glfw.create_window(screen_w, screen_h, "CS2_OVERLAY", None, None)
    if not window:
        glfw.terminate()
        return None
        
    glfw.make_context_current(window)
    glfw.swap_interval(1)
    
    # Делаем окно прозрачным на уровне Windows стилей
    hwnd = glfw.get_win32_window(window)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, 
                           win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)

    imgui.create_context()
    renderer = GlfwRenderer(window)
    return window, renderer, screen_w, screen_h

# ==========================================
# 4. ОСНОВНОЙ ПРОЦЕСС И БЕЗОПАСНЫЙ ЦИКЛ
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
        print("[ERROR] Не удалось создать окно ImGui оверлея.")
        return

    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()
        
        imgui.new_frame()
        imgui.set_next_window_size(float(screen_w), float(screen_h))
        imgui.set_next_window_position(0, 0)
        imgui.begin("OverlayWindow", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        draw_list = imgui.get_window_draw_list()

        try:
            # Чтение матрицы обзора
            view_matrix = [pm.read_float(client_dll + conf["dwViewMatrix"] + (m_idx * 4)) for m_idx in range(16)]
            entity_list = pm.read_longlong(client_dll + conf["dwEntityList"])
            
            if entity_list and entity_list != 0:
                for i in range(64):
                    try:
                        list_entry = pm.read_longlong(entity_list + (i * 0x20))
                        if not list_entry or list_entry == 0:
                            continue

                        player_controller = pm.read_longlong(list_entry + 0x0)
                        if not player_controller or player_controller == 0:
                            continue

                        pawn_handle = pm.read_uint(player_controller + conf["m_hPlayerPawn"])
                        if not pawn_handle or pawn_handle == 0:
                            continue

                        list_entry_pawn = pm.read_longlong(entity_list + (0x8 * ((pawn_handle & 0x7FFF) >> 9) + 0x10))
                        if not list_entry_pawn or list_entry_pawn == 0:
                            continue

                        pawn_ptr = pm.read_longlong(list_entry_pawn + (0x78 * (pawn_handle & 0x1FF)))
                        if not pawn_ptr or pawn_ptr == 0:
                            continue

                        health = pm.read_int(pawn_ptr + conf["m_iHealth"])
                        if health <= 0 or health > 100:
                            continue

                        pos_x = pm.read_float(pawn_ptr + conf["m_vOldOrigin"])
                        pos_y = pm.read_float(pawn_ptr + conf["m_vOldOrigin"] + 4)
                        pos_z = pm.read_float(pawn_ptr + conf["m_vOldOrigin"] + 8)

                        screen_pos = world_to_screen([pos_x, pos_y, pos_z], view_matrix)
                        
                        if screen_pos:
                            sc_x = screen_pos[0] * (screen_w / 2)
                            sc_y = screen_pos[1] * (screen_h / 2)
                            
                            head_pos = world_to_screen([pos_x, pos_y, pos_z + 72.0], view_matrix)
                            if head_pos:
                                h_y = head_pos[1] * (screen_h / 2)
                                box_height = max(5.0, sc_y - h_y)
                                box_width = box_height / 2
                                
                                # Отрисовка бокса
                                draw_list.add_rect(
                                    sc_x - (box_width / 2), h_y,
                                    sc_x + (box_width / 2), sc_y,
                                    imgui.get_color_u32_rgba(0, 1, 0, 1),
                                    thickness=2.0
                                )
                                # Отрисовка здоровья
                                imgui.set_cursor_position((sc_x - 10, h_y - 15))
                                imgui.text_colored(f"{health} HP", 0, 1, 0, 1)

                    except pymem.exception.MemoryReadError:
                        continue

        except pymem.exception.MemoryReadError:
            pass
        except Exception:
            pass

        imgui.end()
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        renderer.render(imgui.get_draw_data())
        glfw.swap_buffers(window)

    renderer.shutdown()
    glfw.terminate()

if __name__ == "__main__":
    main()
