import pymem
import pymem.process
import win32gui, win32con, win32api
import time, os, json, ctypes, math
import imgui
from imgui.integrations.glfw import GlfwRenderer
import glfw
import OpenGL.GL as gl

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except: pass

WINDOW_WIDTH = win32api.GetSystemMetrics(0)
WINDOW_HEIGHT = win32api.GetSystemMetrics(1)

# Глобальные смещения движка
dwEntityList, dwLocalPlayerPawn, dwViewMatrix, dwLocalPlayerController = None, None, None, None
m_iTeamNum, m_hPlayerPawn, m_iHealth, m_vecOrigin, m_pGameSceneNode = None, None, None, None, None
m_modelState, m_entitySpottedState = None, None

pm = None
client = None
config_status = "STABLE"
game_status = "WAITING CS2..."
offsets_loaded = False
stats = {"enemies": 0, "visible": 0}

# Состояние кнопок управления
show_menu = True
enable_esp = True
insert_was_pressed = False
f5_was_pressed = False

# Скелет: пары индексов костей для отрисовки линий
BONE_CONNECTIONS = [
    (6, 5), (5, 4), (4, 0),             # Позвоночник: Голова -> Шея -> Грудь -> Таз
    (5, 8), (8, 9), (9, 11),            # Левая рука
    (5, 13), (13, 14), (14, 16),        # Правая рука
    (0, 22), (22, 23), (23, 24),        # Левая нога
    (0, 25), (25, 26), (26, 27)         # Правая нога
]

def apply_blood_theme():
    """Кастомный черно-красный стиль Blood HUD"""
    style = imgui.get_style()
    style.window_rounding = 6.0
    style.frame_rounding = 4.0
    style.scrollbar_rounding = 3.0
    
    style.colors[imgui.COLOR_WINDOW_BACKGROUND] = [0.03, 0.02, 0.02, 0.88] 
    style.colors[imgui.COLOR_BORDER] = [0.55, 0.0, 0.0, 0.7]              
    style.colors[imgui.COLOR_TITLE_BACKGROUND] = [0.35, 0.0, 0.0, 0.8]     
    style.colors[imgui.COLOR_TITLE_BACKGROUND_ACTIVE] = [0.65, 0.0, 0.0, 0.95] 
    style.colors[imgui.COLOR_TEXT] = [0.92, 0.92, 0.92, 1.0]              
    style.colors[imgui.COLOR_SEPARATOR] = [0.45, 0.0, 0.0, 0.6]           

def load_local_offsets():
    global dwEntityList, dwLocalPlayerPawn, dwViewMatrix, dwLocalPlayerController
    global m_iTeamNum, m_hPlayerPawn, m_iHealth, m_vecOrigin, m_pGameSceneNode
    global m_modelState, m_entitySpottedState, config_status, offsets_loaded

    offsets_path = os.path.join("offsets", "offsets.json")
    client_dll_path = os.path.join("offsets", "client_dll.json")

    if not os.path.exists(offsets_path) or not os.path.exists(client_dll_path):
        config_status = "ERR: JSON MISSING"
        return

    try:
        with open(offsets_path, "r", encoding="utf-8") as f:
            offsets_data = json.load(f)
        with open(client_dll_path, "r", encoding="utf-8") as f:
            client_dll_data = json.load(f)

        dwEntityList = offsets_data['client.dll']['dwEntityList']
        dwLocalPlayerPawn = offsets_data['client.dll']['dwLocalPlayerPawn']
        dwViewMatrix = offsets_data['client.dll']['dwViewMatrix']
        dwLocalPlayerController = offsets_data['client.dll'].get('dwLocalPlayerController', None)

        dw_classes = client_dll_data['client.dll']['classes']
        m_iTeamNum = dw_classes['C_BaseEntity']['fields']['m_iTeamNum']
        m_hPlayerPawn = dw_classes['CCSPlayerController']['fields']['m_hPlayerPawn']
        m_iHealth = dw_classes['C_BaseEntity']['fields']['m_iHealth']
        m_pGameSceneNode = dw_classes['C_BaseEntity']['fields']['m_pGameSceneNode']
        m_vecOrigin = dw_classes['CGameSceneNode']['fields']['m_vecOrigin']
        
        m_modelState = dw_classes['CSkeletonInstance']['fields']['m_modelState']
        m_entitySpottedState = dw_classes.get('C_CSPlayerPawn', {}).get('fields', {}).get('m_entitySpottedState', None)

        config_status = "BLOOD CONFIG LOADED"
        offsets_loaded = True
    except:
        config_status = "PARSER ERR"

def w2s(mtx, posx, posy, posz):
    clipX = posx * mtx[0] + posy * mtx[1] + posz * mtx[2] + mtx[3]
    clipY = posx * mtx[4] + posy * mtx[5] + posz * mtx[6] + mtx[7]
    clipW = posx * mtx[12] + posy * mtx[13] + posz * mtx[14] + mtx[15]
    if clipW > 0.001:
        return [(WINDOW_WIDTH / 2) + (clipX / clipW) * (WINDOW_WIDTH / 2), (WINDOW_HEIGHT / 2) - (clipY / clipW) * (WINDOW_HEIGHT / 2)]
    return None

def get_bone_position(pm, game_scene, bone_index):
    try:
        skeleton_address = game_scene + m_modelState
        bone_array = pm.read_longlong(skeleton_address + 0x80) 
        if not bone_array: return None
        
        bone_address = bone_array + (bone_index * 32)
        bx = pm.read_float(bone_address)
        by = pm.read_float(bone_address + 0x04)
        bz = pm.read_float(bone_address + 0x08)
        
        if bx == 0.0 and by == 0.0: return None
        return [bx, by, bz]
    except: return None

def esp(draw_list):
    global stats
    if not pm or not offsets_loaded or not enable_esp: return
    stats = {"enemies": 0, "visible": 0}

    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
        local_pawn = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_pawn: return
        
        local_team = pm.read_int(local_pawn + m_iTeamNum)
        entity_list = pm.read_longlong(client + dwEntityList)
        if not entity_list: return
        
        local_scene = pm.read_longlong(local_pawn + m_pGameSceneNode)
        lx = pm.read_float(local_scene + m_vecOrigin)
        ly = pm.read_float(local_scene + m_vecOrigin + 0x4)
        lz = pm.read_float(local_scene + m_vecOrigin + 0x8)
    except: return

    local_idx = -1
    if dwLocalPlayerController:
        try:
            local_ctrl = pm.read_longlong(client + dwLocalPlayerController)
            for idx in range(1, 512):
                le = pm.read_longlong(entity_list + 0x10 + 8 * ((idx & 0x7FFF) >> 9))
                if le and pm.read_longlong(le + 112 * (idx & 0x1FF)) == local_ctrl:
                    local_idx = idx
                    break
        except: pass

    # Скан до 512 сущностей гарантирует обнаружение всех отдаленных ботов
    for i in range(1, 512):
        try:
            list_entry = pm.read_longlong(entity_list + 0x10 + 8 * ((i & 0x7FFF) >> 9))
            if not list_entry: continue
            controller = pm.read_longlong(list_entry + 112 * (i & 0x1FF))
            if not controller: continue

            pawn_handle = pm.read_uint(controller + m_hPlayerPawn)
            if not pawn_handle: continue

            list_entry2 = pm.read_longlong(entity_list + 0x10 + 8 * ((pawn_handle & 0x7FFF) >> 9))
            if not list_entry2: continue

            entity_pawn = pm.read_longlong(list_entry2 + 112 * (pawn_handle & 0x1FF))
            if not entity_pawn or entity_pawn == local_pawn: continue

            health = pm.read_int(entity_pawn + m_iHealth)
            if health <= 0 or health > 100: continue

            team = pm.read_int(entity_pawn + m_iTeamNum)
            if team == local_team: continue
            stats["enemies"] += 1

            game_scene = pm.read_longlong(entity_pawn + m_pGameSceneNode)
            if not game_scene: continue

            fx = pm.read_float(game_scene + m_vecOrigin)
            fy = pm.read_float(game_scene + m_vecOrigin + 0x4)
            fz = pm.read_float(game_scene + m_vecOrigin + 0x8)

            dx, dy, dz = fx - lx, fy - ly, fz - lz
            distance_meters = int(math.sqrt(dx*dx + dy*dy + dz*dz) / 39.37)

            is_spotted = False
            if local_idx != -1 and m_entitySpottedState:
                try:
                    slot = local_idx - 1
                    sb = entity_pawn + m_entitySpottedState
                    mask = pm.read_uint(sb + 0xC + (slot // 32) * 4)
                    is_spotted = (mask & (1 << (slot % 32))) != 0
                except: pass

            # Цвета: Зеленый — можно стрелять (виден), Бордовый — скрыт
            if is_spotted:
                stats["visible"] += 1
                color = imgui.get_color_u32_rgba(0.0, 0.95, 0.2, 0.95) # Токсично-зеленый
            else:
                color = imgui.get_color_u32_rgba(0.65, 0.0, 0.0, 0.85) # Кроваво-красный

            head_screen = w2s(view_matrix, fx, fy, fz + 74.0)
            leg_screen = w2s(view_matrix, fx, fy, fz)
            if not head_screen or not leg_screen: continue

            h_diff = abs(head_screen[1] - leg_screen[1])
            w_diff = h_diff / 1.8
            l_x, r_x = head_screen[0] - (w_diff / 2.0), head_screen[0] + (w_diff / 2.0)

            # Отрисовка линий (Snaplines) от центра низа экрана к ногам врага
            draw_list.add_line(WINDOW_WIDTH / 2, WINDOW_HEIGHT, leg_screen[0], leg_screen[1], color, 1.0)

            # Отрисовка Box
            draw_list.add_rect(l_x, head_screen[1], r_x, leg_screen[1], color, rounding=1.0, thickness=1.5)

            # Вертикальный ХП-Бар
            bar_x = l_x - 6
            bar_top = head_screen[1]
            bar_bottom = leg_screen[1]
            bar_height = bar_bottom - bar_top
            
            draw_list.add_rect_filled(bar_x - 1, bar_top, bar_x + 2, bar_bottom, imgui.get_color_u32_rgba(0.02, 0.02, 0.02, 0.6))
            health_perc = max(0, min(100, health)) / 100.0
            hp_bar_top = bar_bottom - (bar_height * health_perc)
            
            hp_color = imgui.get_color_u32_rgba(0.3 + (health_perc * 0.7), 0.1 * health_perc, 0.1 * health_perc, 1.0) if not is_spotted else imgui.get_color_u32_rgba(0.0, 0.9, 0.2, 1.0)
            draw_list.add_rect_filled(bar_x - 1, hp_bar_top, bar_x + 2, bar_bottom, hp_color)

            # Дистанция
            draw_list.add_text(l_x, leg_screen[1] + 2, imgui.get_color_u32_rgba(0.9, 0.9, 0.9, 1.0), f"{distance_meters}m")

            # Рендеринг скелета
            bone_positions_2d = {}
            unique_bones = set([6] + [b for conn in BONE_CONNECTIONS for b in conn])
            
            for bone_id in unique_bones:
                b_pos_3d = get_bone_position(pm, game_scene, bone_id)
                if b_pos_3d:
                    b_pos_2d = w2s(view_matrix, b_pos_3d[0], b_pos_3d[1], b_pos_3d[2])
                    if b_pos_2d: bone_positions_2d[bone_id] = b_pos_2d

            bone_color = imgui.get_color_u32_rgba(0.9, 0.9, 0.9, 0.75)
            for connection in BONE_CONNECTIONS:
                if connection[0] in bone_positions_2d and connection[1] in bone_positions_2d:
                    p1 = bone_positions_2d[connection[0]]
                    p2 = bone_positions_2d[connection[1]]
                    if math.hypot(p1[0]-p2[0], p1[1]-p2[1]) < h_diff * 1.5:
                        draw_list.add_line(p1[0], p1[1], p2[0], p2[1], bone_color, 1.3)

            # Круг на голову
            if 6 in bone_positions_2d:
                head_2d = bone_positions_2d[6]
                dynamic_radius = max(2.5, h_diff / 12.0)
                draw_list.add_circle(head_2d[0], head_2d[1], dynamic_radius, color, num_segments=18, thickness=1.5)
        except: continue

def handle_hotkeys():
    """Обработка нажатий на горячие клавиши без залипаний"""
    global show_menu, enable_esp, insert_was_pressed, f5_was_pressed
    
    # Клавиша INSERT (Скрытие/показ меню настроек)
    if win32api.GetAsyncKeyState(win32con.VK_INSERT) & 0x8000:
        if not insert_was_pressed:
            show_menu = not show_menu
            insert_was_pressed = True
    else:
        insert_was_pressed = False

    # Клавиша F5 (Включение/выключение ВХ)
    if win32api.GetAsyncKeyState(win32con.VK_F5) & 0x8000:
        if not f5_was_pressed:
            enable_esp = not enable_esp
            f5_was_pressed = True
    else:
        f5_was_pressed = False

def try_connect_game():
    global pm, client, game_status
    try:
        process = pymem.process.process_from_name("cs2.exe")
        if process:
            pid = process.th32ProcessID
            handle = ctypes.windll.kernel32.OpenProcess(0x0010 | 0x0400, False, pid)
            if handle:
                pm = pymem.Pymem()
                pm.process_id = pid
                pm.process_handle = handle
                client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
                game_status = "CONNECTED"
                return True
    except: pass
    game_status = "SEARCHING CS2..."
    return False

def main():
    if not glfw.init(): return
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    
    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "BloodHUD", None, None)
    if not window:
        glfw.terminate()
        return

    hwnd = glfw.get_win32_window(window)
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME)
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    glfw.make_context_current(window)
    imgui.create_context()
    
    apply_blood_theme()
    
    impl = GlfwRenderer(window)
    load_local_offsets()
    last_check = 0

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        
        # Сканируем хоткеи каждую итерацию
        handle_hotkeys()
        
        imgui.new_frame()
        
        if not pm and time.time() - last_check > 2.0:
            last_check = time.time()
            try_connect_game()

        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("Canvas", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND)
        if offsets_loaded and pm and enable_esp: 
            esp(imgui.get_window_draw_list())
        imgui.end()

        # Меню BLOOD // EXTERNAL скрывается/открывается по кнопке Insert
        if show_menu:
            imgui.set_next_window_position(25, 25)
            imgui.set_next_window_size(240, 130)
            imgui.begin("BLOOD // EXTERNAL", flags=imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_COLLAPSE)
            imgui.text(f"STATUS: {game_status}")
            imgui.text(f"ESP STATE: {'ENABLED' if enable_esp else 'DISABLED'}")
            imgui.separator()
            imgui.text(f"ENEMIES PARSED: {stats['enemies'] if enable_esp else 0}")
            imgui.text(f"TARGETS VISIBLE: {stats['visible'] if enable_esp else 0}")
            imgui.end()

        imgui.end_frame()
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        impl.render(imgui.get_draw_data())
        glfw.swap_buffers(window)
        time.sleep(0.003)

    impl.shutdown()
    glfw.terminate()

if __name__ == '__main__':
    main()
