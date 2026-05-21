import pymem
import pymem.process
import win32gui, win32con, win32api
import time, os, json, ctypes
import imgui
from imgui.integrations.glfw import GlfwRenderer
import glfw
import OpenGL.GL as gl

# Снятие ограничений по DPI для точных координат боксов
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except: pass

WINDOW_WIDTH = win32api.GetSystemMetrics(0)
WINDOW_HEIGHT = win32api.GetSystemMetrics(1)

# Глобальные переменные смещений
dwEntityList, dwLocalPlayerPawn, dwViewMatrix, dwLocalPlayerController = None, None, None, None
m_iTeamNum, m_hPlayerPawn, m_iHealth, m_vecOrigin, m_pGameSceneNode = None, None, None, None, None
m_entitySpottedState = None

pm = None
client = None
game_status = "Waiting for cs2.exe..."
config_status = "Checking local offsets..."
loop_status = "Initializing..."
offsets_loaded = False
stats = {"checked": 0, "alive": 0, "enemies": 0, "visible": 0}

def load_local_offsets():
    global dwEntityList, dwLocalPlayerPawn, dwViewMatrix, dwLocalPlayerController
    global m_iTeamNum, m_hPlayerPawn, m_iHealth, m_vecOrigin, m_pGameSceneNode, m_entitySpottedState
    global config_status, offsets_loaded

    offsets_path = os.path.join("offsets", "offsets.json")
    client_dll_path = os.path.join("offsets", "client_dll.json")

    if not os.path.exists(offsets_path) or not os.path.exists(client_dll_path):
        config_status = "Error: JSON files not found!"
        offsets_loaded = False
        return

    try:
        with open(offsets_path, "r", encoding="utf-8") as f:
            offsets_data = json.load(f)
        with open(client_dll_path, "r", encoding="utf-8") as f:
            client_dll_data = json.load(f)

        # Считываем адреса из твоих json-файлов
        dwEntityList = offsets_data['client.dll']['dwEntityList']
        dwLocalPlayerPawn = offsets_data['client.dll']['dwLocalPlayerPawn']
        dwViewMatrix = offsets_data['client.dll']['dwViewMatrix']
        dwLocalPlayerController = offsets_data['client.dll'].get('dwLocalPlayerController', None)

        # Считываем смещения полей
        m_iTeamNum = client_dll_data['client.dll']['classes']['C_BaseEntity']['fields']['m_iTeamNum']
        m_hPlayerPawn = client_dll_data['client.dll']['classes']['CCSPlayerController']['fields']['m_hPlayerPawn']
        m_iHealth = client_dll_data['client.dll']['classes']['C_BaseEntity']['fields']['m_iHealth']
        m_vecOrigin = client_dll_data['client.dll']['classes']['CGameSceneNode']['fields']['m_vecOrigin']
        m_pGameSceneNode = client_dll_data['client.dll']['classes']['C_BaseEntity']['fields']['m_pGameSceneNode']
        
        m_entitySpottedState = client_dll_data['client.dll']['classes'].get('C_CSPlayerPawn', {}).get('fields', {}).get('m_entitySpottedState', None)

        config_status = "Offsets applied successfully!"
        offsets_loaded = True
    except Exception as e:
        config_status = f"Parser Error: {str(e)}"
        offsets_loaded = False

def w2s(mtx, posx, posy, posz, width, height):
    clipX = posx * mtx[0] + posy * mtx[1] + posz * mtx[2] + mtx[3]
    clipY = posx * mtx[4] + posy * mtx[5] + posz * mtx[6] + mtx[7]
    clipW = posx * mtx[12] + posy * mtx[13] + posz * mtx[14] + mtx[15]

    if clipW > 0.001:
        x = (width / 2) + (clipX / clipW) * (width / 2)
        y = (height / 2) - (clipY / clipW) * (height / 2)
        return [x, y]
    return [-999, -999]

def esp(draw_list):
    global stats, pm, client, offsets_loaded, loop_status
    if not pm or not client or not offsets_loaded: 
        loop_status = "Sleep (No Game Context)"
        return

    stats = {"checked": 0, "alive": 0, "enemies": 0, "visible": 0}

    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
        local_player_pawn = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_player_pawn:
            loop_status = "Main Menu / Loading"
            return
        
        local_team = pm.read_int(local_player_pawn + m_iTeamNum)
        entity_list = pm.read_longlong(client + dwEntityList)
        if not entity_list: return
    except:
        return

    # Определяем индекс локального игрока для проверки SpottedMask
    local_idx = -1
    if dwLocalPlayerController:
        try:
            local_controller = pm.read_longlong(client + dwLocalPlayerController)
            for idx in range(1, 64):
                le = pm.read_longlong(entity_list + (((8 * (idx & 0x7FFF)) >> 9) + 16))
                if le:
                    pc = pm.read_longlong(le + 112 * (idx & 0x1FF))
                    if pc == local_controller:
                        local_idx = idx
                        break
        except:
            pass

    loop_status = "Active Scanning..."

    # Проходим по циклу контроллеров (максимум 64 игрока на сервере)
    for i in range(1, 64):
        try:
            # 1. Читаем запись первого уровня (Контроллеры)
            list_entry = pm.read_longlong(entity_list + ((8 * (i & 0x7FFF)) >> 9) + 16)
            if not list_entry: continue

            player_controller = pm.read_longlong(list_entry + 112 * (i & 0x1FF))
            if not player_controller: continue

            stats["checked"] += 1

            # 2. Получаем хэндл на Pawn
            pawn_handle = pm.read_uint(player_controller + m_hPlayerPawn)
            if not pawn_handle: continue

            # 3. Находим запись второго уровня (Резолв Pawn)
            # ВНИМАНИЕ: Для маски здесь используется 0x1FF, как и в оригинальной структуре движка Source 2
            list_entry2 = pm.read_longlong(entity_list + (8 * ((pawn_handle & 0x7FFF) >> 9) + 16))
            if not list_entry2: continue

            entity_pawn = pm.read_longlong(list_entry2 + 112 * (pawn_handle & 0x1FF))
            if not entity_pawn or entity_pawn == local_player_pawn: continue

            # 4. Валидация здоровья
            health = pm.read_int(entity_pawn + m_iHealth)
            if health <= 0 or health > 100: continue
            stats["alive"] += 1

            # 5. Проверка на команду (убираем союзников)
            team = pm.read_int(entity_pawn + m_iTeamNum)
            if team == local_team: continue
            stats["enemies"] += 1

            # 6. Получение координат через GameSceneNode
            game_scene = pm.read_longlong(entity_pawn + m_pGameSceneNode)
            if not game_scene: continue

            feetX = pm.read_float(game_scene + m_vecOrigin)
            feetY = pm.read_float(game_scene + m_vecOrigin + 0x4)
            feetZ = pm.read_float(game_scene + m_vecOrigin + 0x8)

            # 7. Проверка видимости на радаре (m_bSpottedByMask)
            is_spotted = False
            if local_idx != -1 and m_entitySpottedState:
                try:
                    player_slot = local_idx - 1
                    spotted_base = entity_pawn + m_entitySpottedState
                    part = player_slot // 32
                    bit = player_slot % 32
                    mask = pm.read_uint(spotted_base + 0xC + part * 4)
                    is_spotted = (mask & (1 << bit)) != 0
                except:
                    pass

            if is_spotted:
                stats["visible"] += 1
                box_color = imgui.get_color_u32_rgba(0.2, 1.0, 0.2, 1.0) # Зеленый — виден
            else:
                box_color = imgui.get_color_u32_rgba(1.0, 0.2, 0.2, 1.0) # Красный — скрыт

            # Трансляция 3D мира в 2D экран
            head_pos = w2s(view_matrix, feetX, feetY, feetZ + 72.0, WINDOW_WIDTH, WINDOW_HEIGHT)
            leg_pos = w2s(view_matrix, feetX, feetY, feetZ, WINDOW_WIDTH, WINDOW_HEIGHT)

            if head_pos[0] == -999 or leg_pos[0] == -999: continue

            # Отрисовка геометрии бокса
            height_diff = abs(head_pos[1] - leg_pos[1])
            width_diff = height_diff / 1.8
            
            left_x = head_pos[0] - (width_diff / 2.0)
            right_x = head_pos[0] + (width_diff / 2.0)

            draw_list.add_rect(left_x, head_pos[1], right_x, leg_pos[1], box_color, rounding=3.0, thickness=2.0)
            draw_list.add_text(left_x, leg_pos[1] + 2, box_color, f"HP: {health}")
        except:
            continue

def try_connect_game():
    global pm, client, game_status
    try:
        process = pymem.process.process_from_name("cs2.exe")
        if process:
            pid = process.th32ProcessID
            # Открываем дескриптор БЕЗ прав Администратора (только чтение и инфо)
            PROCESS_VM_READ = 0x0010
            PROCESS_QUERY_INFORMATION = 0x0400
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
            
            if handle:
                pm = pymem.Pymem()
                pm.process_id = pid
                pm.process_handle = handle
                client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
                game_status = "Connected to CS2 (User Mode)"
                return True
    except:
        pass
    game_status = "Searching for cs2.exe..."
    return False

def main():
    global pm, client, game_status
    if not glfw.init(): return
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    
    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "VibeHUD", None, None)
    if not window:
        glfw.terminate()
        return

    hwnd = glfw.get_win32_window(window)
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    style &= ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME)
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    
    ex_style = win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)

    load_local_offsets()
    last_check = 0

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()
        
        current_time = time.time()
        if not pm and current_time - last_check > 2.0:
            last_check = current_time
            try_connect_game()

        # Полноэкранный невидимый холст для отрисовки боксов
        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("Canvas", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_SCROLLBAR | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_BACKGROUND)
        
        draw_list = imgui.get_window_draw_list()
        if offsets_loaded and pm:
            esp(draw_list)
            
        imgui.end()

        # UI Панель дебага
        imgui.set_next_window_position(20, 20)
        imgui.set_next_window_size(310, 180)
        imgui.begin("Vibe HUD Pro", flags=imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_COLLAPSE)
        imgui.text(f"Offsets Status: {config_status}")
        imgui.text(f"Game Status: {game_status}")
        imgui.text(f"Thread State: {loop_status}")
        imgui.separator()
        imgui.text(f"Entities Found: {stats['checked']}")
        imgui.text(f"Valid Pawns: {stats['alive']}")
        imgui.text(f"Enemies Parsed: {stats['enemies']}")
        imgui.text(f"Visible (Spotted): {stats['visible']}")
        imgui.end()

        imgui.end_frame()
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        impl.render(imgui.get_draw_data())
        glfw.swap_buffers(window)
        
        time.sleep(0.004) # Ограничение фреймрейта для разгрузки процессора

    impl.shutdown()
    glfw.terminate()

if __name__ == '__main__':
    main()
