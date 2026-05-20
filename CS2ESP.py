import pymem
import pymem.process
import win32gui, win32con
import time, os
import imgui
from imgui.integrations.glfw import GlfwRenderer
import glfw
import OpenGL.GL as gl
import requests

WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080

print("[INFO] Загрузка актуальных оффсетов...")
try:
    offsets = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json').json()
    client_dll = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json').json()
except Exception as e:
    print(f"[ERROR] Не удалось загрузить оффсеты из сети: {e}")
    exit(1)

dwEntityList = offsets['client.dll']['dwEntityList']
dwLocalPlayerPawn = offsets['client.dll']['dwLocalPlayerPawn']
dwViewMatrix = offsets['client.dll']['dwViewMatrix']

m_iTeamNum = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iTeamNum']
m_lifeState = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_lifeState']
m_pGameSceneNode = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_pGameSceneNode']
m_iHealth = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iHealth']

print("[INFO] Ожидание запуска cs2.exe...")
while True:
    time.sleep(1)
    try:
        pm = pymem.Pymem("cs2.exe")
        client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
        print("[SUCCESS] CS2 найдена! Процесс подключен.")
        break
    except:
        pass

time.sleep(1)
os.system("cls")

last_log_time = 0

def w2s(mtx, posx, posy, posz, width, height):
    screenW = mtx[12]*posx + mtx[13]*posy + mtx[14]*posz + mtx[15]
    if screenW > 0.001:
        screenX = mtx[0]*posx + mtx[1]*posy + mtx[2]*posz + mtx[3]
        screenY = mtx[4]*posx + mtx[5]*posy + mtx[6]*posz + mtx[7]
        camX = width / 2
        camY = height / 2
        x = camX + (camX * screenX / screenW)
        y = camY - (camY * screenY / screenW)
        return [x, y]
    return None

def esp(draw_list):
    global last_log_time
    current_time = time.time()
    should_log = (current_time - last_log_time) > 3.0
    if should_log:
        last_log_time = current_time
        print("\n--- [LOG] Новый цикл проверки игроков ---")

    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
        local_player = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_player:
            if should_log: print("[LOG] Локальный игрок не найден (вы зашли на сервер?)")
            return
        local_team = pm.read_int(local_player + m_iTeamNum)
    except Exception as e:
        if should_log: print(f"[LOG] Ошибка чтения базовых данных: {e}")
        return

    entity_list = pm.read_longlong(client + dwEntityList)
    if not entity_list:
        if should_log: print("[LOG] Не удалось прочитать EntityList")
        return

    players_found = 0
    players_drawn = 0

    # Перебираем игроков (максимум 64 в CS2)
    for i in range(1, 64):
        try:
            # Получаем элемент списка контроллеров
            list_entry1 = pm.read_longlong(entity_list + ((8 * (i & 0x7FFF) >> 9) + 16))
            if not list_entry1: continue

            controller = pm.read_longlong(list_entry1 + 120 * (i & 0x1FF))
            if not controller: continue

            # Из контроллера достаем хэндл Pawn игрока
            m_hPlayerPawn = pm.read_int(controller + client_dll['client.dll']['classes']['CCSPlayerController']['fields']['m_hPlayerPawn'])
            if not m_hPlayerPawn: continue

            # По хэндлу находим сам Pawn в памяти
            list_entry2 = pm.read_longlong(entity_list + (0x8 * ((m_hPlayerPawn & 0x7FFF) >> 9) + 16))
            if not list_entry2: continue

            pawn = pm.read_longlong(list_entry2 + 120 * (m_hPlayerPawn & 0x1FF))
            if not pawn or pawn == local_player: continue

            players_found += 1

            # Проверка на команду (пропускаем тиммейтов)
            team = pm.read_int(pawn + m_iTeamNum)
            if team == local_team: continue

            # Проверка здоровья и статуса жизнедеятельности
            health = pm.read_int(pawn + m_iHealth)
            life_state = pm.read_int(pawn + m_lifeState)
            if health <= 0 or life_state != 0: continue

            # Получаем координаты сцены для поиска костей/позиции
            game_scene = pm.read_longlong(pawn + m_pGameSceneNode)
            if not game_scene: continue

            # Смещение костей в CS2 (NodePosition + ModelState)
            # Для стабильности берем координаты напрямую из сцены (позиция ног)
            pos_x = pm.read_float(game_scene + client_dll['client.dll']['classes']['CGameSceneNode']['fields']['m_vecAbsOrigin'])
            pos_y = pm.read_float(game_scene + client_dll['client.dll']['classes']['CGameSceneNode']['fields']['m_vecAbsOrigin'] + 4)
            pos_z = pm.read_float(game_scene + client_dll['client.dll']['classes']['CGameSceneNode']['fields']['m_vecAbsOrigin'] + 8)

            # Проекция на экран
            leg_pos = w2s(view_matrix, pos_x, pos_y, pos_z, WINDOW_WIDTH, WINDOW_HEIGHT)
            head_pos = w2s(view_matrix, pos_x, pos_y, pos_z + 72.0, WINDOW_WIDTH, WINDOW_HEIGHT) # 72 единицы вверх — средний рост модели

            if not leg_pos or not head_pos: continue

            # Расчет размеров 2D бокса
            height = abs(leg_pos[1] - head_pos[1])
            width = height / 2.0

            left_x = head_pos[0] - width / 2.0
            right_x = head_pos[0] + width / 2.0

            color = imgui.get_color_u32_rgba(1.0, 0.0, 0.0, 1.0) # Ярко-красный

            # Отрисовка рамки бокса
            draw_list.add_line(left_x, leg_pos[1], right_x, leg_pos[1], color, 1.5)
            draw_list.add_line(left_x, leg_pos[1], left_x, head_pos[1], color, 1.5)
            draw_list.add_line(right_x, leg_pos[1], right_x, head_pos[1], color, 1.5)
            draw_list.add_line(left_x, head_pos[1], right_x, head_pos[1], color, 1.5)

            # Отрисовка ХП
            draw_list.add_text(left_x - 25, head_pos[1], color, f"{health} HP")
            players_drawn += 1

        except:
            continue

    if should_log:
        print(f"[LOG] Всего активных Pawn найдено: {players_found} | Отрисовано врагов: {players_drawn}")

def main():
    if not glfw.init():
        print("[ERROR] Не удалось инициализировать GLFW")
        return

    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE) # Поверх всех окон
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)

    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "CS2 Overlay", None, None)
    if not window:
        glfw.terminate()
        return

    hwnd = glfw.get_win32_window(window)
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    style &= ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME)
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    
    ex_style = win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, WINDOW_WIDTH, WINDOW_HEIGHT,
                          win32con.SWP_NOMOVE | win32con.SWP_NOACTIVATE)

    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)

    print("[SUCCESS] Оверлей запущен успешно. Свернитесь в игру (оно должно быть в оконном/оконном без рамки режиме).")

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()

        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("OverlayWindow",
                    flags=imgui.WINDOW_NO_TITLE_BAR |
                          imgui.WINDOW_NO_RESIZE |
                          imgui.WINDOW_NO_SCROLLBAR |
                          imgui.WINDOW_NO_COLLAPSE |
                          imgui.WINDOW_NO_BACKGROUND)

        draw_list = imgui.get_window_draw_list()
        esp(draw_list)

        imgui.end()
        imgui.end_frame()

        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        impl.render(imgui.get_draw_data())
        glfw.swap_buffers(window)

    impl.shutdown()
    glfw.terminate()

if __name__ == '__main__':
    main()
