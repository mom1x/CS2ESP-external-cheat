import pymem
import pymem.process
import win32gui, win32con, win32api
import time, os, json
import imgui
from imgui.integrations.glfw import GlfwRenderer
import glfw
import OpenGL.GL as gl

# Автоопределение разрешения экрана
WINDOW_WIDTH = win32api.GetSystemMetrics(0)
WINDOW_HEIGHT = win32api.GetSystemMetrics(1)

# Глобальные переменные для смещений
dwEntityList, dwLocalPlayerPawn, dwViewMatrix = None, None, None
m_iTeamNum, m_lifeState, m_pGameSceneNode = None, None, None
m_modelState, m_hPlayerPawn, m_iHealth = None, None, None

pm = None
client = None
game_status = "Waiting for cs2.exe..."
config_status = "Checking local offsets..."
offsets_loaded = False
stats = {"checked": 0, "alive": 0, "enemies": 0, "on_screen": 0}

def load_local_offsets():
    global dwEntityList, dwLocalPlayerPawn, dwViewMatrix
    global m_iTeamNum, m_lifeState, m_pGameSceneNode, m_modelState, m_hPlayerPawn, m_iHealth
    global config_status, offsets_loaded

    offsets_path = os.path.join("offsets", "offsets.json")
    client_dll_path = os.path.join("offsets", "client_dll.json")

    if not os.path.exists(offsets_path) or not os.path.exists(client_dll_path):
        config_status = "Error: JSON files not found in /offsets/"
        offsets_loaded = False
        return

    try:
        with open(offsets_path, "r", encoding="utf-8") as f:
            offsets_data = json.load(f)
        with open(client_dll_path, "r", encoding="utf-8") as f:
            client_dll_data = json.load(f)

        # Парсим структуры (поддерживает стандартный формат cs2-dumper от a2x)
        dwEntityList = offsets_data['client.dll']['dwEntityList']
        dwLocalPlayerPawn = offsets_data['client.dll']['dwLocalPlayerPawn']
        dwViewMatrix = offsets_data['client.dll']['dwViewMatrix']

        m_iTeamNum = client_dll_data['client.dll']['classes']['C_BaseEntity']['fields']['m_iTeamNum']
        m_lifeState = client_dll_data['client.dll']['classes']['C_BaseEntity']['fields']['m_lifeState']
        m_pGameSceneNode = client_dll_data['client.dll']['classes']['C_BaseEntity']['fields']['m_pGameSceneNode']
        m_modelState = client_dll_data['client.dll']['classes']['CSkeletonInstance']['fields']['m_modelState']
        m_hPlayerPawn = client_dll_data['client.dll']['classes']['CCSPlayerController']['fields']['m_hPlayerPawn']
        m_iHealth = client_dll_data['client.dll']['classes']['C_BaseEntity']['fields']['m_iHealth']

        config_status = "Offsets loaded successfully!"
        offsets_loaded = True
    except Exception as e:
        config_status = f"Parser Error: {str(e)}"
        offsets_loaded = False

def w2s(mtx, posx, posy, posz, width, height):
    clipX = posx * mtx[0] + posy * mtx[4] + posz * mtx[8] + mtx[12]
    clipY = posx * mtx[1] + posy * mtx[5] + posz * mtx[9] + mtx[13]
    clipW = posx * mtx[3] + posy * mtx[7] + posz * mtx[11] + mtx[15]

    if clipW > 0.001:
        x = (width / 2) + (clipX / clipW) * (width / 2)
        y = (height / 2) - (clipY / clipW) * (height / 2)
        return [x, y]
    return [-999, -999]

def esp(draw_list):
    global stats, pm, client, offsets_loaded
    if not pm or not client or not offsets_loaded: return

    stats = {"checked": 0, "alive": 0, "enemies": 0, "on_screen": 0}

    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
        local_player = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_player: return
        local_team = pm.read_int(local_player + m_iTeamNum)
    except:
        return

    for i in range(64):
        try:
            entity = pm.read_longlong(client + dwEntityList)
            if not entity: continue

            list_entry = pm.read_longlong(entity + (0x8 * (i >> 9) + 16))
            if not list_entry: continue

            entity_controller = pm.read_longlong(list_entry + 120 * (i & 0x1FF))
            if not entity_controller: continue

            # Читаем хэндл пешки как 4-байтовое число (int)
            entity_controller_pawn = pm.read_int(entity_controller + m_hPlayerPawn)
            if not entity_controller_pawn: continue

            list_entry2 = pm.read_longlong(entity + (0x8 * ((entity_controller_pawn & 0x7FFF) >> 9) + 16))
            if not list_entry2: continue

            entity_pawn = pm.read_longlong(list_entry2 + 120 * (entity_controller_pawn & 0x1FF))
            if not entity_pawn or entity_pawn == local_player: continue

            stats["checked"] += 1

            if pm.read_int(entity_pawn + m_lifeState) != 0: continue
            stats["alive"] += 1

            if pm.read_int(entity_pawn + m_iTeamNum) == local_team: continue
            stats["enemies"] += 1

            # Позиции костей
            game_scene = pm.read_longlong(entity_pawn + m_pGameSceneNode)
            bone_matrix = pm.read_longlong(game_scene + m_modelState + 0x80)

            headX = pm.read_float(bone_matrix + 6 * 0x20)
            headY = pm.read_float(bone_matrix + 6 * 0x20 + 0x4)
            headZ = pm.read_float(bone_matrix + 6 * 0x20 + 0x8) + 6
            head_pos = w2s(view_matrix, headX, headY, headZ, WINDOW_WIDTH, WINDOW_HEIGHT)

            legZ = pm.read_float(bone_matrix + 28 * 0x20 + 0x8)
            leg_pos = w2s(view_matrix, headX, headY, legZ, WINDOW_WIDTH, WINDOW_HEIGHT)

            if head_pos[0] == -999 or leg_pos[0] == -999: continue
            stats["on_screen"] += 1

            # Отрисовка
            color = imgui.get_color_u32_rgba(1, 0, 0, 1)
            delta = abs(head_pos[1] - leg_pos[1])
            leftX = head_pos[0] - delta // 3
            rightX = head_pos[0] + delta // 3

            draw_list.add_line(leftX,  leg_pos[1],  rightX, leg_pos[1],  color, 2.0)
            draw_list.add_line(leftX,  leg_pos[1],  leftX,  head_pos[1], color, 2.0)
            draw_list.add_line(rightX, leg_pos[1],  rightX, head_pos[1], color, 2.0)
            draw_list.add_line(leftX,  head_pos[1], rightX, head_pos[1], color, 2.0)

            entity_hp = pm.read_int(entity_pawn + m_iHealth)
            draw_list.add_text(leftX - 25, head_pos[1] - 5, color, f"HP: {entity_hp}")
        except:
            continue

def main():
    global pm, client, game_status
    if not glfw.init(): return
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    
    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "overlay", None, None)
    if not window:
        glfw.terminate()
        return

    hwnd = glfw.get_win32_window(window)
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    style &= ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME)
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    
    ex_style = win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, -2, -2, 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)

    # Пробуем прочитать локальные файлы при старте
    load_local_offsets()

    last_check = 0

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()
        
        # Подключение к процессу игры
        current_time = time.time()
        if not pm and current_time - last_check > 1.0:
            last_check = current_time
            try:
                pm = pymem.Pymem("cs2.exe")
                client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
                game_status = "CS2 Connected!"
            except:
                game_status = "Waiting for cs2.exe..."

        # Фоновый прозрачный слой под ESP боксы
        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("overlay", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_SCROLLBAR | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_BACKGROUND)
        
        draw_list = imgui.get_window_draw_list()
        if offsets_loaded:
            esp(draw_list)
            
        imgui.end()

        # Debug HUD для мониторинга прямо на экране
        imgui.set_next_window_position(10, 10)
        imgui.set_next_window_size(320, 150)
        imgui.begin("Local Loader Debug HUD", flags=imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_COLLAPSE)
        imgui.text(f"Offsets: {config_status}")
        imgui.text(f"Game Proc: {game_status}")
        imgui.separator()
        imgui.text(f"Entities Checked: {stats['checked']}")
        imgui.text(f"Alive Players: {stats['alive']}")
        imgui.text(f"Enemies Found: {stats['enemies']}")
        imgui.text(f"Rendered Boxes: {stats['on_screen']}")
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
