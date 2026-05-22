import pymem
import pymem.process
import win32gui, win32con, win32api
import time, os, json, ctypes, math, struct
import threading
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
SCREEN_CENTER_X = WINDOW_WIDTH / 2
SCREEN_CENTER_Y = WINDOW_HEIGHT / 2

# Смещения базовые
dwEntityList, dwLocalPlayerPawn, dwViewMatrix, dwLocalPlayerController, dwViewAngles = None, None, None, None, None
m_iTeamNum, m_hPlayerPawn, m_iHealth, m_vecOrigin, m_pGameSceneNode = None, None, None, None, None
m_modelState, m_entitySpottedState, m_vecViewOffset = None, None, None
# Смещения для системы наблюдателей
m_pObserverServices, m_hObserverTarget, m_sSanitizedPlayerName = None, None, None

pm = None
client = None
config_status = "STABLE"
game_status = "WAITING CS2..."
offsets_loaded = False
stats = {"enemies": 0, "visible": 0}
spectators_list = []
local_idx_global = -1

menu_open = True            
cfg_show_hud_stats = True   

# Настройки систем
cfg_esp_enabled = True      # Глобальный переключатель ВХ (F8)
cfg_esp_box = True
cfg_esp_skeleton = True
cfg_esp_tracers = False
cfg_aim_enabled = True
cfg_aim_ignore_visibility = True  
cfg_aim_fov = 15.0        
cfg_aim_smooth = 4.0      
cfg_aim_bone = 6          

BONE_CONNECTIONS = [
    (6, 5), (5, 4), (4, 0),              
    (5, 8), (8, 9), (9, 11),            
    (5, 13), (13, 14), (14, 16),        
    (0, 22), (22, 23), (23, 24),        
    (0, 25), (25, 26), (26, 27)         
]

def apply_blood_theme():
    style = imgui.get_style()
    style.window_rounding = 6.0
    style.frame_rounding = 4.0
    style.scrollbar_rounding = 3.0
    style.colors[imgui.COLOR_WINDOW_BACKGROUND] = [0.04, 0.03, 0.03, 0.95] 
    style.colors[imgui.COLOR_BORDER] = [0.6, 0.0, 0.0, 0.75]              
    style.colors[imgui.COLOR_TITLE_BACKGROUND] = [0.38, 0.0, 0.0, 0.85]     
    style.colors[imgui.COLOR_TITLE_BACKGROUND_ACTIVE] = [0.7, 0.0, 0.0, 1.0] 
    style.colors[imgui.COLOR_TEXT] = [0.95, 0.95, 0.95, 1.0]              
    style.colors[imgui.COLOR_SEPARATOR] = [0.5, 0.0, 0.0, 0.6]            
    style.colors[imgui.COLOR_FRAME_BACKGROUND] = [0.12, 0.05, 0.05, 0.8]
    style.colors[imgui.COLOR_FRAME_BACKGROUND_HOVERED] = [0.25, 0.05, 0.05, 0.9]
    style.colors[imgui.COLOR_FRAME_BACKGROUND_ACTIVE] = [0.4, 0.05, 0.05, 1.0]
    style.colors[imgui.COLOR_SLIDER_GRAB] = [0.7, 0.0, 0.0, 1.0]
    style.colors[imgui.COLOR_SLIDER_GRAB_ACTIVE] = [0.9, 0.0, 0.0, 1.0]

def update_window_input_state(hwnd, is_clickable):
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    if is_clickable:
        style &= ~win32con.WS_EX_TRANSPARENT  
    else:
        style |= win32con.WS_EX_TRANSPARENT   
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)

def force_focus_game():
    hwnd_cs2 = win32gui.FindWindow(None, "Counter-Strike 2")
    if hwnd_cs2:
        try: win32gui.SetForegroundWindow(hwnd_cs2)
        except: pass

def load_local_offsets():
    global dwEntityList, dwLocalPlayerPawn, dwViewMatrix, dwLocalPlayerController, dwViewAngles
    global m_iTeamNum, m_hPlayerPawn, m_iHealth, m_pGameSceneNode, m_vecOrigin, m_vecViewOffset
    global m_modelState, m_entitySpottedState, config_status, offsets_loaded
    global m_pObserverServices, m_hObserverTarget, m_sSanitizedPlayerName

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
        dwViewAngles = offsets_data['client.dll']['dwViewAngles']
        dwLocalPlayerController = offsets_data['client.dll'].get('dwLocalPlayerController', None)

        dw_classes = client_dll_data['client.dll']['classes']
        m_iTeamNum = dw_classes['C_BaseEntity']['fields']['m_iTeamNum']
        m_hPlayerPawn = dw_classes['CCSPlayerController']['fields']['m_hPlayerPawn']
        m_iHealth = dw_classes['C_BaseEntity']['fields']['m_iHealth']
        m_pGameSceneNode = dw_classes['C_BaseEntity']['fields']['m_pGameSceneNode']
        m_vecOrigin = dw_classes['CGameSceneNode']['fields']['m_vecOrigin']
        m_vecViewOffset = dw_classes['C_BaseModelEntity']['fields']['m_vecViewOffset']
        
        m_modelState = dw_classes['CSkeletonInstance']['fields']['m_modelState']
        m_entitySpottedState = dw_classes.get('C_CSPlayerPawn', {}).get('fields', {}).get('m_entitySpottedState', None)
        
        m_pObserverServices = dw_classes.get('C_BasePlayerPawn', {}).get('fields', {}).get('m_pObserverServices', None)
        m_hObserverTarget = dw_classes.get('C_PlayerObserverServices', {}).get('fields', {}).get('m_hObserverTarget', None)
        m_sSanitizedPlayerName = dw_classes.get('CCSPlayerController', {}).get('fields', {}).get('m_sSanitizedPlayerName', None)

        config_status = "MULTIHACK CFG LOADED"
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

def get_bone_position(pm, bone_array, bone_index):
    try:
        bone_address = bone_array + (bone_index * 32)
        b_bytes = pm.read_bytes(bone_address, 12)
        bx, by, bz = struct.unpack('fff', b_bytes)
        if bx == 0.0 and by == 0.0: return None
        return [bx, by, bz]
    except: return None

def async_aimbot_processor():
    global pm, client, offsets_loaded, cfg_aim_enabled, cfg_aim_fov, cfg_aim_smooth, cfg_aim_bone, cfg_aim_ignore_visibility, local_idx_global
    
    while True:
        time.sleep(0.001)  
        
        if not pm or not offsets_loaded or not cfg_aim_enabled:
            continue
            
        if (win32api.GetAsyncKeyState(0x01) & 0x8000) == 0:
            continue
            
        try:
            v_buff = pm.read_bytes(client + dwViewMatrix, 64)
            view_matrix = struct.unpack('16f', v_buff)
            
            local_pawn = pm.read_longlong(client + dwLocalPlayerPawn)
            if not local_pawn: continue
            
            local_team = pm.read_int(local_pawn + m_iTeamNum)
            entity_list = pm.read_longlong(client + dwEntityList)
            if not entity_list: continue
            
            fov_pixels = (cfg_aim_fov * WINDOW_WIDTH) / 180.0
            
            best_target_dx = None
            best_target_dy = None
            min_screen_dist = fov_pixels
            
            list_entry = pm.read_longlong(entity_list + 16) 
            if not list_entry: continue
            
            for slot in range(1, 64):
                try:
                    controller = pm.read_longlong(list_entry + 112 * slot)
                    if not controller: continue
                    
                    team = pm.read_int(controller + m_iTeamNum)
                    if team not in [2, 3] or team == local_team: continue
                    
                    pawn_handle = pm.read_uint(controller + m_hPlayerPawn)
                    if not pawn_handle or pawn_handle == 0xFFFFFFFF: continue
                    
                    pawn_chunk = (pawn_handle & 0x7FFF) >> 9
                    pawn_slot = pawn_handle & 0x1FF
                    
                    list_entry2 = pm.read_longlong(entity_list + 8 * pawn_chunk + 16)
                    if not list_entry2: continue
                    
                    entity_pawn = pm.read_longlong(list_entry2 + 112 * pawn_slot)
                    if not entity_pawn or entity_pawn == local_pawn: continue
                    
                    health = pm.read_int(entity_pawn + m_iHealth)
                    if health <= 0 or health > 200: continue
                    
                    if not cfg_aim_ignore_visibility and local_idx_global != -1 and m_entitySpottedState:
                        try:
                            slot_idx = local_idx_global - 1
                            sb = entity_pawn + m_entitySpottedState
                            mask = pm.read_uint(sb + 0xC + (slot_idx // 32) * 4)
                            if not (mask & (1 << (slot_idx % 32))): continue
                        except: pass
                        
                    game_scene = pm.read_longlong(entity_pawn + m_pGameSceneNode)
                    skeleton_address = game_scene + m_modelState
                    bone_array = pm.read_longlong(skeleton_address + 0x80)
                    if not bone_array: continue
                    
                    bone_pos3d = get_bone_position(pm, bone_array, cfg_aim_bone)
                    if bone_pos3d:
                        bone_screen = w2s(view_matrix, bone_pos3d[0], bone_pos3d[1], bone_pos3d[2])
                        if bone_screen:
                            dx = bone_screen[0] - SCREEN_CENTER_X
                            dy = bone_screen[1] - SCREEN_CENTER_Y
                            dist = math.hypot(dx, dy)
                            
                            if dist < min_screen_dist:
                                min_screen_dist = dist
                                best_target_dx = dx
                                best_target_dy = dy
                except: continue
                
            if best_target_dx is not None and best_target_dy is not None:
                move_x = best_target_dx / max(1.0, cfg_aim_smooth)
                move_y = best_target_dy / max(1.0, cfg_aim_smooth)
                win32api.mouse_event(win32con.MOUSEEVENTF_MOVE, int(move_x), int(move_y), 0, 0)
        except: pass

def process_visuals_and_sync(draw_list):
    global stats, local_idx_global, spectators_list, cfg_esp_enabled
    if not pm or not offsets_loaded: return
    
    current_stats = {"enemies": 0, "visible": 0}
    current_spectators = []
    
    try:
        v_buff = pm.read_bytes(client + dwViewMatrix, 64)
        view_matrix = struct.unpack('16f', v_buff)
        local_pawn = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_pawn: return
        
        local_team = pm.read_int(local_pawn + m_iTeamNum)
        entity_list = pm.read_longlong(client + dwEntityList)
        if not entity_list: return
        
        local_pawn_handle = 0
        if dwLocalPlayerController:
            local_ctrl = pm.read_longlong(client + dwLocalPlayerController)
            if local_ctrl:
                local_pawn_handle = pm.read_uint(local_ctrl + m_hPlayerPawn)

        list_entry = pm.read_longlong(entity_list + 16)
        if list_entry:
            # Сканируем до 128 слотов контроллеров для больших серверов сообщества
            for slot in range(1, 128):
                try:
                    controller = pm.read_longlong(list_entry + 112 * slot)
                    if not controller: continue
                    
                    # Получаем хэндл Pawn сущности напрямую из контроллера игрока
                    pawn_handle = pm.read_uint(controller + m_hPlayerPawn)
                    if not pawn_handle or pawn_handle == 0xFFFFFFFF: continue
                    
                    # Декодируем хэндл для поиска в структуре EntityList
                    pawn_chunk = (pawn_handle & 0x7FFF) >> 9
                    pawn_slot = pawn_handle & 0x1FF
                    list_entry2 = pm.read_longlong(entity_list + 8 * pawn_chunk + 16)
                    if not list_entry2: continue
                    
                    entity_pawn = pm.read_longlong(list_entry2 + 112 * pawn_slot)
                    if not entity_pawn: continue

                    # --- ИСПРАВЛЕННАЯ И НАДЕЖНАЯ ЛОГИКА НАБЛЮДАТЕЛЕЙ ---
                    if local_pawn_handle and m_pObserverServices and m_hObserverTarget:
                        try:
                            obs_services = pm.read_longlong(entity_pawn + m_pObserverServices)
                            if obs_services:
                                target_handle = pm.read_uint(obs_services + m_hObserverTarget)
                                # Проверяем, совпадает ли цель наблюдения с нашим хэндлом
                                if target_handle == local_pawn_handle and entity_pawn != local_pawn:
                                    name_ptr = pm.read_longlong(controller + m_sSanitizedPlayerName)
                                    if name_ptr:
                                        name_bytes = pm.read_bytes(name_ptr, 64)
                                        s_name = name_bytes.split(b'\x00')[0].decode('utf-8', errors='ignore')
                                    else:
                                        s_name = f"Player ({slot})"
                                        
                                    if s_name and s_name not in current_spectators:
                                        current_spectators.append(s_name)
                        except: pass

                    # Если F8 выключил отображение, то визуалы не рисуем, но сбор спектаторов выше все равно сработал!
                    if not cfg_esp_enabled:
                        continue

                    # Ограничение игрового рендера для ESP (стандартные 64 слота активных игроков)
                    if slot > 64: continue
                    if entity_pawn == local_pawn: continue
                    
                    team = pm.read_int(controller + m_iTeamNum)
                    if team not in [2, 3] or team == local_team: continue
                    
                    health = pm.read_int(entity_pawn + m_iHealth)
                    if health <= 0 or health > 200: continue
                    
                    current_stats["enemies"] += 1
                    
                    is_spotted = False
                    if local_idx_global != -1 and m_entitySpottedState:
                        slot_idx = local_idx_global - 1
                        sb = entity_pawn + m_entitySpottedState
                        mask = pm.read_uint(sb + 0xC + (slot_idx // 32) * 4)
                        is_spotted = (mask & (1 << (slot_idx % 32))) != 0
                        
                    if is_spotted: current_stats["visible"] += 1
                    
                    game_scene = pm.read_longlong(entity_pawn + m_pGameSceneNode)
                    f_bytes = pm.read_bytes(game_scene + m_vecOrigin, 12)
                    fx, fy, fz = struct.unpack('fff', f_bytes)
                    
                    head_screen = w2s(view_matrix, fx, fy, fz + 73.0)
                    leg_screen = w2s(view_matrix, fx, fy, fz)
                    if not head_screen or not leg_screen: continue
                    
                    color = imgui.get_color_u32_rgba(0.0, 1.0, 0.2, 0.95) if is_spotted else imgui.get_color_u32_rgba(0.55, 0.0, 0.0, 0.85)
                    h_diff = abs(head_screen[1] - leg_screen[1])
                    w_diff = h_diff / 1.8
                    l_x, r_x = head_screen[0] - (w_diff / 2.0), head_screen[0] + (w_diff / 2.0)
                    
                    if cfg_esp_box:
                        draw_list.add_rect(l_x, head_screen[1], r_x, leg_screen[1], color, rounding=1.0, thickness=1.5)
                    if cfg_esp_tracers:
                        draw_list.add_line(SCREEN_CENTER_X, WINDOW_HEIGHT, leg_screen[0], leg_screen[1], color, 1.0)
                        
                    bar_x = l_x - 6
                    draw_list.add_rect_filled(bar_x - 1, head_screen[1], bar_x + 2, leg_screen[1], imgui.get_color_u32_rgba(0.02, 0.02, 0.02, 0.6))
                    health_perc = max(0, min(100, health)) / 100.0
                    draw_list.add_rect_filled(bar_x - 1, leg_screen[1] - (h_diff * health_perc), bar_x + 2, leg_screen[1], imgui.get_color_u32_rgba(0.3 + (health_perc * 0.7), 0.1, 0.1, 1.0))
                    
                    if cfg_esp_skeleton:
                        skeleton_address = game_scene + m_modelState
                        bone_array = pm.read_longlong(skeleton_address + 0x80)
                        if bone_array:
                            bone_positions_2d = {}
                            for bone_id in set([6] + [b for conn in BONE_CONNECTIONS for b in conn]):
                                b_pos_3d = get_bone_position(pm, bone_array, bone_id)
                                if b_pos_3d:
                                    b_pos_2d = w2s(view_matrix, b_pos_3d[0], b_pos_3d[1], b_pos_3d[2])
                                    if b_pos_2d: bone_positions_2d[bone_id] = b_pos_2d
                            for conn in BONE_CONNECTIONS:
                                if conn[0] in bone_positions_2d and conn[1] in bone_positions_2d:
                                    p1, p2 = bone_positions_2d[conn[0]], bone_positions_2d[conn[1]]
                                    if math.hypot(p1[0]-p2[0], p1[1]-p2[1]) < h_diff * 1.5:
                                        draw_list.add_line(p1[0], p1[1], p2[0], p2[1], imgui.get_color_u32_rgba(0.9, 0.9, 0.9, 0.75), 1.3)
                            if 6 in bone_positions_2d:
                                draw_list.add_circle(bone_positions_2d[6][0], bone_positions_2d[6][1], max(2.5, h_diff / 12.0), color, num_segments=16, thickness=1.5)
                except: continue
    except: pass
    if cfg_esp_enabled:
        stats = current_stats
    spectators_list = current_spectators

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
    global cfg_esp_enabled, cfg_esp_box, cfg_esp_skeleton, cfg_esp_tracers
    global cfg_aim_enabled, cfg_aim_fov, cfg_aim_smooth, cfg_aim_bone, cfg_aim_ignore_visibility, menu_open, cfg_show_hud_stats
    global local_idx_global, spectators_list

    if not glfw.init(): return
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    
    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "BloodHUD_Pro", None, None)
    if not window:
        glfw.terminate()
        return

    hwnd = glfw.get_win32_window(window)
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE) & ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME)
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, win32con.WS_EX_LAYERED)
    update_window_input_state(hwnd, menu_open)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    glfw.make_context_current(window)
    glfw.swap_interval(1)
    imgui.create_context()
    apply_blood_theme()
    
    impl = GlfwRenderer(window)
    load_local_offsets()
    
    aim_thread = threading.Thread(target=async_aimbot_processor, daemon=True)
    aim_thread.start()
    
    last_check = 0
    last_local_idx_check = 0

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()
        
        # Переключение меню (F5)
        if win32api.GetAsyncKeyState(win32con.VK_F5) & 1:
            menu_open = not menu_open
            update_window_input_state(hwnd, menu_open)
            if not menu_open:
                force_focus_game()

        if win32api.GetAsyncKeyState(win32con.VK_F6) & 1:
            cfg_show_hud_stats = not cfg_show_hud_stats

        if win32api.GetAsyncKeyState(win32con.VK_F7) & 1:
            cfg_aim_enabled = not cfg_aim_enabled

        # Переключатель ВХ (F8)
        if win32api.GetAsyncKeyState(win32con.VK_F8) & 1:
            cfg_esp_enabled = not cfg_esp_enabled

        # Поиск игры
        if not pm and time.time() - last_check > 2.0:
            last_check = time.time()
            try_connect_game()

        if pm and offsets_loaded and (time.time() - last_local_idx_check > 1.5):
            last_local_idx_check = time.time()
            try:
                local_ctrl = pm.read_longlong(client + dwLocalPlayerController)
                entity_list = pm.read_longlong(client + dwEntityList)
                list_entry_local = pm.read_longlong(entity_list + 16)
                if list_entry_local and local_ctrl:
                    for slot in range(64):
                        if pm.read_longlong(list_entry_local + 112 * slot) == local_ctrl:
                            local_idx_global = slot
                            break
            except: pass

        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("Canvas", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        imgui.get_window_draw_list().add_text(15, WINDOW_HEIGHT - 45, imgui.get_color_u32_rgba(1.0, 1.0, 1.0, 0.4), "[F5] Menu  |  [F6] HUD Widgets  |  [F7] Toggle Aim  |  [F8] Toggle ESP")
        
        if offsets_loaded and pm: 
            process_visuals_and_sync(imgui.get_window_draw_list())
            if cfg_aim_enabled:
                fov_pixels = (cfg_aim_fov * WINDOW_WIDTH) / 180.0
                imgui.get_window_draw_list().add_circle(SCREEN_CENTER_X, SCREEN_CENTER_Y, fov_pixels, imgui.get_color_u32_rgba(0.6, 0.0, 0.0, 0.25), num_segments=48, thickness=1.2)
        imgui.end()

        # Виджеты HUD справа
        if cfg_show_hud_stats:
            # 1. Основной системный виджет
            imgui.set_next_window_position(WINDOW_WIDTH - 240, 30, condition=imgui.ALWAYS)
            imgui.set_next_window_size(220, 150)
            imgui.begin("HUD_STATUS_PANEL", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
            
            dl = imgui.get_window_draw_list()
            pos = imgui.get_window_position()
            size = imgui.get_window_size()
            dl.add_rect_filled(pos.x, pos.y, pos.x + size.x, pos.y + size.y, imgui.get_color_u32_rgba(0.04, 0.03, 0.03, 0.8), rounding=5.0)
            dl.add_rect(pos.x, pos.y, pos.x + size.x, pos.y + size.y, imgui.get_color_u32_rgba(0.6, 0.0, 0.0, 0.75), rounding=5.0, thickness=1.5)
            
            imgui.set_cursor_pos((12, 10))
            imgui.text_colored("BLOODHUD SYSTEM", 0.9, 0.0, 0.0, 1.0)
            imgui.separator()
            
            g_color = [0.0, 1.0, 0.2, 1.0] if game_status == "CONNECTED" else [0.8, 0.1, 0.1, 1.0]
            imgui.text("Link Status: ")
            imgui.same_line()
            imgui.text_colored(game_status, *g_color)
            
            esp_stat_color = [0.0, 1.0, 0.2, 1.0] if cfg_esp_enabled else [0.8, 0.1, 0.1, 1.0]
            imgui.text("Visuals (F8): ")
            imgui.same_line()
            imgui.text_colored("ACTIVE" if cfg_esp_enabled else "MUTED", *esp_stat_color)
            
            a_color = [0.0, 1.0, 0.2, 1.0] if cfg_aim_enabled else [0.5, 0.5, 0.5, 1.0]
            imgui.text("Aimbot Logic: ")
            imgui.same_line()
            imgui.text_colored("MOUSE SIM" if cfg_aim_enabled else "MUTED", *a_color)
            
            imgui.text(f"Targets Tracked: {stats['enemies'] if cfg_esp_enabled else 0}")
            imgui.end()

            # 2. Выровненный по правому краю список наблюдателей
            if spectators_list:
                imgui.set_next_window_position(WINDOW_WIDTH - 240, 195, condition=imgui.ALWAYS)
                imgui.set_next_window_size(220, 35 + len(spectators_list) * 20)
                imgui.begin("HUD_SPEC_PANEL", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
                
                sdl = imgui.get_window_draw_list()
                spos = imgui.get_window_position()
                ssize = imgui.get_window_size()
                sdl.add_rect_filled(spos.x, spos.y, spos.x + ssize.x, spos.y + ssize.y, imgui.get_color_u32_rgba(0.04, 0.03, 0.03, 0.85), rounding=5.0)
                sdl.add_rect(spos.x, spos.y, spos.x + ssize.x, spos.y + ssize.y, imgui.get_color_u32_rgba(0.8, 0.0, 0.0, 0.85), rounding=5.0, thickness=1.5)
                
                imgui.set_cursor_pos((12, 8))
                imgui.text_colored("WATCHING YOU:", 1.0, 0.1, 0.1, 1.0)
                imgui.separator()
                
                for spec_name in spectators_list:
                    imgui.set_cursor_pos((12, imgui.get_cursor_pos().y + 2))
                    imgui.text_colored(f"👁 {spec_name}", 0.95, 0.95, 0.95, 1.0)
                imgui.end()

        if menu_open:
            imgui.set_next_window_position(60, 60, condition=imgui.FIRST_USE_EVER)
            imgui.set_next_window_size(460, 340, condition=imgui.FIRST_USE_EVER)
            imgui.begin("BLOODWARE // MULTIHACK V2", flags=imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_COLLAPSE)
            
            imgui.text(f"Status: {game_status} | Config: {config_status}")
            imgui.separator()

            if imgui.begin_tab_bar("CheatTabs"):
                if imgui.begin_tab_item("VISUALS")[0]:
                    imgui.spacing()
                    _, cfg_esp_enabled = imgui.checkbox("Master ESP Toggle (F8)", cfg_esp_enabled)
                    imgui.separator()
                    _, cfg_esp_box = imgui.checkbox("Enable 2D Box ESP", cfg_esp_box)
                    _, cfg_esp_skeleton = imgui.checkbox("Enable Skeleton Bones", cfg_esp_skeleton)
                    _, cfg_esp_tracers = imgui.checkbox("Enable Snaplines", cfg_esp_tracers)
                    imgui.end_tab_item()

                if imgui.begin_tab_item("AIMBOT")[0]:
                    imgui.spacing()
                    _, cfg_aim_enabled = imgui.checkbox("Enable Mouse Aimbot", cfg_aim_enabled)
                    _, cfg_aim_ignore_visibility = imgui.checkbox("Ignore Visibility (For Deathmatch)", cfg_aim_ignore_visibility)
                    imgui.separator()
                    
                    _, cfg_aim_fov = imgui.slider_float("FOV Radius", cfg_aim_fov, 1.0, 45.0, "%.1f deg")
                    _, cfg_aim_smooth = imgui.slider_float("Smoothing (Lower = Faster)", cfg_aim_smooth, 1.0, 25.0, "%.1f")
                    
                    imgui.spacing()
                    imgui.text("Target Bone Position:")
                    if imgui.radio_button("Head (Bone 6)", cfg_aim_bone == 6): cfg_aim_bone = 6
                    imgui.same_line()
                    if imgui.radio_button("Neck (Bone 5)", cfg_aim_bone == 5): cfg_aim_bone = 5
                    imgui.same_line()
                    if imgui.radio_button("Chest (Bone 4)", cfg_aim_bone == 4): cfg_aim_bone = 4
                    imgui.end_tab_item()
            imgui.end_tab_bar()
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
