import os
import json
import time
import pymem
import pymem.exception
import glfw
import OpenGL.GL as gl
import imgui
from imgui.integrations.glfw import GlfwRenderer

# ==========================================
# 1. ЗАГРУЗКА ОФФСЕТОВ ИЗ JSON
# ==========================================
def load_offsets():
    print("[INFO] Загрузка встроенных оффсетов из папки offsets...")
    try:
        # Пути к файлам, которые скачивает твой GitHub Workflow
        offsets_path = os.path.join("offsets", "offsets.json")
        client_dll_path = os.path.join("offsets", "client_dll.json")

        with open(offsets_path, "r") as f:
            offsets = json.load(f)["client.dll"]
        with open(client_dll_path, "r") as f:
            client_data = json.load(f)["client.dll"]["classes"]

        # Извлекаем нужные оффсеты (имена соответствуют дамперу a2x)
        return {
            "dwEntityList": offsets["dwEntityList"],
            "dwViewMatrix": offsets["dwViewMatrix"],
            "dwLocalPlayerPawn": offsets["dwLocalPlayerPawn"],
            # Смещения для классов (проверяем разные варианты именования в дампере)
            "m_iHealth": client_data.get("C_BaseEntity", {}).get("fields", {}).get("m_iHealth", 0x32C),
            "m_hPlayerPawn": client_data.get("CCSPlayerController", {}).get("fields", {}).get("m_hPlayerPawn", 0x7BC),
            "m_vOldOrigin": client_data.get("C_BasePlayerPawn", {}).get("fields", {}).get("m_vOldOrigin", 0x1274),
            "m_iTeamNum": client_data.get("C_BaseEntity", {}).get("fields", {}).get("m_iTeamNum", 0x3bf)
        }
    except Exception as e:
        print(f"[ERROR] Ошибка загрузки JSON конфигурации оффсетов: {e}")
        # Запасные хардкод значения, если JSON не прочитался
        return {
            "dwEntityList": 0x18C2DB8, "dwViewMatrix": 0x19242A0, "dwLocalPlayerPawn": 0x1823A08,
            "m_iHealth": 0x32C, "m_hPlayerPawn": 0x7BC, "m_vOldOrigin": 0x1274, "m_iTeamNum": 0x3bf
        }

# ==========================================
# 2. МАТЕМАТИКА (WORLD TO SCREEN)
# ==========================================
def world_to_screen(pos, matrix):
    # pos = [x, y, z]
    # matrix = список из 16 элементов фрейма матрицы
    w = matrix[12] * pos[0] + matrix[13] * pos[1] + matrix[14] * pos[2] + matrix[15]
    if w < 0.01:
        return None
    
    x = matrix[0] * pos[0] + matrix[1] * pos[1] + matrix[2] * pos[2] + matrix[3]
    y = matrix[4] * pos[0] + matrix[5] * pos[1] + matrix[6] * pos[2] + matrix[7]
    
    # Нормализация координат под экран
    screen_x = (x / w) + 1.0
    screen_y = 1.0 - (y / w)
    
    # Рассчитываем относительно разрешения окна (будет обновляться в цикле)
    return screen_x, screen_y

# ==========================================
# 3. ИНИЦИАЛИЗАЦИЯ GLFW И IMGUI ОВЕРЛЕЯ
# ==========================================
def init_overlay():
    if not glfw.init():
        return None
    
    # Настройки для создания полностью прозрачного окна поверх игры
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.MOUSE_PASSTHROUGH, glfw.TRUE) # Клики проходят сквозь окно в игру

    # Получаем разрешение монитора для оверлея
    monitor = glfw.get_primary_monitor()
    mode = glfw.get_video_mode(monitor)
    
    window = glfw.create_window(mode.width, mode.height, "CS2_OVERLAY", None, None)
    if not window:
        glfw.terminate()
        return None
        
    glfw.make_context_current(window)
    glfw.swap_interval(1) # Включаем вертикальную синхронизацию для стабильного FPS
    
    imgui.create_context()
    renderer = GlfwRenderer(window)
    return window, renderer, mode.width, mode.height

# ==========================================
# 4. ОСНОВНОЙ ПРОЦЕСС И БЕЗОПАСНЫЙ ЦИКЛ
# ==========================================
def main():
    conf = load_offsets()
    print("[INFO] Ожидание запуска CS2...")
    
    pm = None
    client_dll = None
    
    # Бесконечный цикл поиска процесса игры
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

    # Инициализируем графическое окно оверлея
    window, renderer, screen_w, screen_h = init_overlay()
    if not window:
        print("[ERROR] Не удалось создать окно ImGui оверлея.")
        return

    # Главный цикл отрисовки
    while not glfw.window_should_close(window):
        glfw.poll_events()
        renderer.process_inputs()
        
        imgui.new_frame()
        # Создаем прозрачный холст на весь экран монитора
        imgui.set_next_window_size(screen_w, screen_h)
        imgui.set_next_window_position(0, 0)
        imgui.begin("OverlayWindow", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        draw_list = imgui.get_window_draw_list()

        try:
            # Читаем матрицу обзора (ViewMatrix состоит из 16 значений float, то есть 64 байта)
            view_matrix_bytes = pm.read_bytes(client_dll + conf["dwViewMatrix"], 64)
            view_matrix = [struct_unpack('f', view_matrix_bytes[i:i+4])[0] for i in range(0, 64, 4)] if 'struct_unpack' in globals() else []
            
            # Если struct не импортирован, прочитаем проще через цикл для стабильности:
            view_matrix = []
            for m_idx in range(16):
                view_matrix.append(pm.read_float(client_dll + conf["dwViewMatrix"] + (m_idx * 4)))

            # Безопасно получаем адрес списка сущностей
            entity_list = pm.read_longlong(client_dll + conf["dwEntityList"])
            
            if entity_list and entity_list != 0:
                # Перебираем все 64 слота под игроков на сервере
                for i in range(64):
                    try:
                        # 1. Валидация ячейки списка
                        list_entry = pm.read_longlong(entity_list + (i * 0x20))
                        if not list_entry or list_entry == 0:
                            continue # Слот пуст — прыгаем дальше БЕЗ ошибок доступа

                        # 2. Валидация контроллера игрока
                        player_controller = pm.read_longlong(list_entry + 0x0)
                        if not player_controller or player_controller == 0:
                            continue

                        # 3. Находим хэндл (ID) физического объекта игрока (Pawn)
                        pawn_handle = pm.read_uint(player_controller + conf["m_hPlayerPawn"])
                        if not pawn_handle or pawn_handle == 0:
                            continue

                        # 4. Находим адрес Pawn в памяти через хэндл-биты
                        list_entry_pawn = pm.read_longlong(entity_list + (0x8 * ((pawn_handle & 0x7FFF) >> 9) + 0x10))
                        if not list_entry_pawn or list_entry_pawn == 0:
                            continue

                        pawn_ptr = pm.read_longlong(list_entry_pawn + (0x78 * (pawn_handle & 0x1FF)))
                        if not pawn_ptr or pawn_ptr == 0:
                            continue

                        # 5. Читаем данные живого игрока
                        health = pm.read_int(pawn_ptr + conf["m_iHealth"])
                        if health <= 0 or health > 100:
                            continue # Игрок мертв или данные некорректны

                        # Получаем координаты ног игрока на карте
                        pos_x = pm.read_float(pawn_ptr + conf["m_vOldOrigin"])
                        pos_y = pm.read_float(pawn_ptr + conf["m_vOldOrigin"] + 4)
                        pos_z = pm.read_float(pawn_ptr + conf["m_vOldOrigin"] + 8)

                        # Переводим 3D координаты игры в 2D координаты твоего экрана
                        screen_pos = world_to_screen([pos_x, pos_y, pos_z], view_matrix)
                        
                        if screen_pos:
                            # Проекция на разрешение экрана
                            sc_x = screen_pos[0] * (screen_w / 2)
                            sc_y = screen_pos[1] * (screen_h / 2)
                            
                            # Рассчитываем примерную высоту бокса в зависимости от дистанции
                            head_pos = world_to_screen([pos_x, pos_y, pos_z + 72.0], view_matrix)
                            if head_pos:
                                h_y = head_pos[1] * (screen_h / 2)
                                box_height = max(5.0, sc_y - h_y)
                                box_width = box_height / 2
                                
                                # ОТРИСОВКА ГЕОМЕТРИИ (Твоя кастомная логика GUI)
                                # Рисуем зеленый квадрат вокруг валидного игрока
                                draw_list.add_rect(
                                    sc_x - (box_width / 2), h_y,
                                    sc_x + (box_width / 2), sc_y,
                                    imgui.get_color_u32_rgba(0, 1, 0, 1), # Зеленый цвет
                                    thickness=2.0
                                )
                                # Выводим текст здоровья над боксом
                                imgui.set_cursor_position((sc_x - 10, h_y - 15))
                                imgui.text_colored(f"{health} HP", 0, 1, 0, 1)

                    except pymem.exception.MemoryReadError:
                        # Если произошла непредвиденная ошибка чтения конкретного адреса —
                        # перехватываем её и идем дальше без вылетов программы.
                        continue

        except pymem.exception.MemoryReadError:
            # Перехват ошибки чтения базовых структур (например при смене карты)
            pass
        except Exception as main_loop_err:
            # Ловим остальные критические ошибки, чтобы оверлей не падал
            pass

        imgui.end()
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        renderer.render(imgui.get_draw_data())
        glfw.swap_buffers(window)

    # Корректное закрытие ресурсов при выходе
    renderer.shutdown()
    glfw.terminate()

if __name__ == "__main__":
    main()
