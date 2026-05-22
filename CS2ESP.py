import pymem
import pymem.process
import win32gui, win32con, win32api
import time, os, json, ctypes, math, struct
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

# Смещения
dwEntityList, dwLocalPlayerPawn, dwViewMatrix, dwLocalPlayerController, dwViewAngles = None, None, None, None, None
m_iTeamNum, m_hPlayerPawn, m_iHealth, m_vecOrigin, m_pGameSceneNode = None, None, None, None, None
m_modelState, m_entitySpottedState, m_vecViewOffset = None, None, None

pm = None
client = None
config_status = "STABLE"
game_status = "WAITING CS2..."
offsets_loaded = False
stats = {"enemies": 0, "visible": 0}

# Состояние меню
menu_open = True  # По умолчанию открыто при старте

# Настройки конфигурации
cfg_esp_box = True
cfg_esp_skeleton = True
cfg_esp_tracers = False
cfg_aim_enabled = True
cfg_aim_ignore_visibility = True  # По умолчанию ВКЛ для идеальной работы с ботами
cfg_aim_fov = 15.0
cfg_aim_smooth = 4.5
cfg_aim_bone = 6  # 6 - Голова

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
    """Динамически переключает кликабельность оверлея"""
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    if is_clickable:
        style &= ~win32con.WS_EX_TRANSPARENT  # Убираем прозрачность для кликов
    else:
        style |= win32con.WS_EX_TRANSPARENT   # Делаем сквозным
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)

def load_local_offsets():
    global dwEntityList, dwLocalPlayerPawn, dwViewMatrix, dwLocalPlayerController, dwViewAngles
    global m_iTeamNum, m_hPlayerPawn, m_iHealth, m_vecOrigin, m_pGameSceneNode
    global m_modelState, m_entitySpottedState, m_vecViewOffset, config_status, offsets_loaded

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

def normalize_angles(pitch, yaw):
    if pitch > 89.0: pitch = 89.0
    if pitch < -89.0: pitch = -89.0
    while yaw > 180.0: yaw -= 360.0
    while yaw < -180.0: yaw += 360.0
    return pitch, yaw

def process_features(draw_list):
    global stats
    if not pm or not offsets_loaded: return
    stats = {"enemies": 0, "visible": 0}

    try:
        v_buff = pm.read_bytes(client + dwViewMatrix, 64)
        view_matrix = struct.unpack('16f', v_buff)

        local_pawn = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_pawn: return
        
        local_team = pm.read_int(local_pawn + m_iTeamNum)
        entity_list = pm.read_longlong(client + dwEntityList)
        if not entity_list: return
        
        local_scene = pm.read_longlong(local_pawn + m_pGameSceneNode)
        l_bytes = pm.read_bytes(local_scene + m_vecOrigin, 12)
        lx, ly, lz = struct.unpack('fff', l_bytes)

        try:
            v_offset_bytes = pm.read_bytes(local_pawn + m_vecViewOffset, 12)
            vox, voy, voz = struct.unpack('fff', v_offset_bytes)
            local_eye_pos = [lx + vox, ly + voy, lz + voz]
        except:
            local_eye_pos = [lx, ly, lz + 64.0]
    except: return

    is_shooting = (win32api.GetAsyncKeyState(0x01) & 0x8000) != 0
    best_target_angles = None
    min_fov_delta = cfg_aim_fov

    local_idx = -1
    if dwLocalPlayerController:
        try:
            local_ctrl = pm.read_longlong(client + dwLocalPlayerController)
            for chunk in range(4):
                le = pm.read_longlong(entity_list + 8 * chunk + 16)
                if not le: continue
                for slot in range(512):
                    if pm.read_longlong(le + 112 * slot) == local_ctrl:
                        local_idx = chunk * 512 + slot
                        break
                if local_idx != -1: break
        except: pass

    # Сбор данных игроков
    for chunk in range(4):
        try:
            list_entry = pm.read_longlong(entity_list + 8 * chunk + 16)
            if not list_entry: continue
        except: continue

        for slot in range(512):
            if chunk == 0 and slot == 0: continue
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

                game_scene = pm.read_longlong(entity_pawn + m_pGameSceneNode)
                if not game_scene: continue

                f_bytes = pm.read_bytes(game_scene + m_vecOrigin, 12)
                fx, fy, fz = struct.unpack('fff', f_bytes)
                if fx == 0.0 and fy == 0.0 and fz == 0.0: continue

                stats["enemies"] += 1

                # Проверка видимости
                is_spotted = False
                if local_idx != -1 and m_entitySpottedState:
                    try:
                        slot_idx = local_idx - 1
                        sb = entity_pawn + m_entitySpottedState
                        mask = pm.read_uint(sb + 0xC + (slot_idx // 32) * 4)
                        is_spotted = (mask & (1 << (slot_idx % 32))) != 0
                    except: pass

                if is_spotted: stats["visible"] += 1

                skeleton_address = game_scene + m_modelState
                bone_array = pm.read_longlong(skeleton_address + 0x80)
                if not bone_array: continue

                aim_bone_pos3d = get_bone_position(pm, bone_array, cfg_aim_bone)
                
                # Логика выбора цели аимботом
                if aim_bone_pos3d and cfg_aim_enabled:
                    # Если включен игнор видимости ИЛИ игрок реально виден
                    if cfg_aim_ignore_visibility or is_spotted:
                        current_pitch = pm.read_float(client + dwViewAngles)
                        current_yaw = pm.read_float(client + dwViewAngles + 4)

                        dx = aim_bone_pos3d[0] - local_eye_pos[0]
                        dy = aim_bone_pos3d[1] - local_eye_pos[1]
                        dz = aim_bone_pos3d[2] - local_eye_pos[2]
                        
                        hypot_2d = math.hypot(dx, dy)
                        target_pitch = -math.atan2(dz, hypot_2d) * 180.0 / math.pi
                        target_yaw = math.atan2(dy, dx) * 180.0 / math.pi
                        
                        delta_p = target_pitch - current_pitch
                        delta_y = target_yaw - current_yaw
                        delta_p, delta_y = normalize_angles(delta_p, delta_y)
                        
                        calculated_fov = math.hypot(delta_p, delta_y)
                        if calculated_fov < min_fov_delta:
                            min_fov_delta = calculated_fov
                            best_target_angles = (target_pitch, target_yaw)

                # --- РЕНДЕРИНГ VISUALS ---
                color = imgui.get_color_u32_rgba(0.0, 1.0, 0.2, 0.95) if is_spotted else imgui.get_color_u32_rgba(0.55, 0.0, 0.0, 0.85)

                head_screen = w2s(view_matrix, fx, fy, fz + 73.0)
                leg_screen = w2s(view_matrix, fx, fy, fz)
                if not head_screen or not leg_screen: continue

                h_diff = abs(head_screen[1] - leg_screen[1])
                w_diff = h_diff / 1.8
                l_x, r_x = head_screen[0] - (w_diff / 2.0), head_screen[0] + (w_diff / 2.0)

                if cfg_esp_box:
                    draw_list.add_rect(l_x, head_screen[1], r_x, leg_screen[1], color, rounding=1.0, thickness=1.5)
                if cfg_esp_tracers:
                    draw_list.add_line(SCREEN_CENTER_X, WINDOW_HEIGHT, leg_screen[0], leg_screen[1], color, 1.0)

                # ХП
                bar_x = l_x - 6
                draw_list.add_rect_filled(bar_x - 1, head_screen[1], bar_x + 2, leg_screen[1], imgui.get_color_u32_rgba(0.02, 0.02, 0.02, 0.6))
                health_perc = max(0, min(100, health)) / 100.0
                hp_bar_top = leg_screen[1] - (h_diff * health_perc)
                draw_list.add_rect_filled(bar_x - 1, hp_bar_top, bar_x + 2, leg_screen[1], imgui.get_color_u32_rgba(0.3 + (health_perc * 0.7), 0.1, 0.1, 1.0))

                # Скелет
                if cfg_esp_skeleton:
                    bone_positions_2d = {}
                    unique_bones = set([6] + [b for conn in BONE_CONNECTIONS for b in conn])
                    for bone_id in unique_bones:
                        b_pos_3d = get_bone_position(pm, bone_array, bone_id)
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
                    if 6 in bone_positions_2d:
                        draw_list.add_circle(bone_positions_2d[6][0], bone_positions_2d[6][1], max(2.5, h_diff / 12.0), color, num_segments=16, thickness=1.5)
            except: continue

    # --- ЗАПИСЬ АИМБОТА В ПАМЯТЬ ---
    if cfg_aim_enabled and is_shooting and best_target_angles:
        try:
            current_pitch = pm.read_float(client + dwViewAngles)
            current_yaw = pm.read_float(client + dwViewAngles + 4)

            target_p, target_y = best_target_angles
            delta_p = target_p - current_pitch
            delta_y = target_y - current_yaw
            delta_p, delta_y = normalize_angles(delta_p, delta_y)

            smooth_factor = max(1.0, cfg_aim_smooth)
            final_pitch = current_pitch + (delta_p / smooth_factor)
            final_yaw = current_yaw + (delta_y / smooth_factor)
            final_pitch, final_yaw = normalize_angles(final_pitch, final_yaw)

            pm.write_float(client + dwViewAngles, final_pitch)
            pm.write_float(client + dwViewAngles + 4, final_yaw)
        except: pass

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
    global cfg_esp_box, cfg_esp_skeleton, cfg_esp_tracers
    global cfg_aim_enabled, cfg_aim_fov, cfg_aim_smooth, cfg_aim_bone, cfg_aim_ignore_visibility, menu_open

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
    
    # Первичная настройка стилей (Изначально меню открыто -> окно кликабельно)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, win32con.WS_EX_LAYERED)
    update_window_input_state(hwnd, menu_open)
    
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    glfw.make_context_current(window)
    glfw.swap_interval(1)
    imgui.create_context()
    apply_blood_theme()
    
    impl = GlfwRenderer(window)
    load_local_offsets()
    last_check = 0

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()
        
        # Переключение видимости меню и КЛИКАБЕЛЬНОСТИ по кнопке INSERT
        if win32api.GetAsyncKeyState(win32con.VK_INSERT) & 1:
            menu_open = not menu_open
            update_window_input_state(hwnd, menu_open)

        # Быстрый бинд F7 (работает всегда)
        if win32api.GetAsyncKeyState(win32con.VK_F7) & 1:
            cfg_aim_enabled = not cfg_aim_enabled

        if not pm and time.time() - last_check > 2.0:
            last_check = time.time()
            try_connect_game()

        # Фоновый холст для ESP и Фова
        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("Canvas", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        # Текстовая подсказка по биндам в углу экрана
        imgui.get_window_draw_list().add_text(15, WINDOW_HEIGHT - 45, imgui.get_color_u32_rgba(1.0, 1.0, 1.0, 0.6), "[INSERT] Show/Hide Menu   |   [F7] Toggle Aimbot")
        
        if offsets_loaded and pm: 
            process_features(imgui.get_window_draw_list())
            if cfg_aim_enabled:
                fov_pixels = (cfg_aim_fov * WINDOW_WIDTH) / 180.0
                imgui.get_window_draw_list().add_circle(SCREEN_CENTER_X, SCREEN_CENTER_Y, fov_pixels, imgui.get_color_u32_rgba(0.6, 0.0, 0.0, 0.3), num_segments=48, thickness=1.2)
        imgui.end()

        # Интерактивное меню (рендерится только если menu_open == True)
        if menu_open:
            imgui.set_next_window_position(50, 50, condition=imgui.FIRST_USE_EVER)
            imgui.set_next_window_size(460, 320, condition=imgui.FIRST_USE_EVER)
            imgui.begin("BLOODWARE // MULTIHACK V2", flags=imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_COLLAPSE)
            
            imgui.text(f"Status: {game_status} | Config: {config_status}")
            imgui.separator()

            if imgui.begin_tab_bar("CheatTabs"):
                # ВКЛАДКА 1: ESP
                if imgui.begin_tab_item("VISUALS")[0]:
                    imgui.spacing()
                    _, cfg_esp_box = imgui.checkbox("Enable 2D Box ESP", cfg_esp_box)
                    _, cfg_esp_skeleton = imgui.checkbox("Enable Skeleton Bones", cfg_esp_skeleton)
                    _, cfg_esp_tracers = imgui.checkbox("Enable Snaplines", cfg_esp_tracers)
                    imgui.separator()
                    imgui.text(f"Enemies cached: {stats['enemies']}")
                    imgui.text(f"Visible points: {stats['visible']}")
                    imgui.end_tab_item()

                # ВКЛАДКА 2: Настройка AIMBOT (Полностью кликабельная!)
                if imgui.begin_tab_item("AIMBOT")[0]:
                    imgui.spacing()
                    aim_status = "ACTIVE" if cfg_aim_enabled else "MUTED"
                    _, cfg_aim_enabled = imgui.checkbox(f"Enable Aimbot Lock ({aim_status})", cfg_aim_enabled)
                    
                    # Фикс для ботов!
                    _, cfg_aim_ignore_visibility = imgui.checkbox("Ignore Visibility Check (For Bots / DM)", cfg_aim_ignore_visibility)
                    if imgui.is_item_hovered():
                        imgui.set_tooltip("Рекомендуется включить для ботов, так как игра не всегда обновляет их статус видимости.")
                    
                    imgui.separator()
                    
                    # Ползунки теперь реагируют идеально
                    _, cfg_aim_fov = imgui.slider_float("FOV Radius", cfg_aim_fov, 1.0, 45.0, "%.1f deg")
                    _, cfg_aim_smooth = imgui.slider_float("Smoothing Speed", cfg_aim_smooth, 1.0, 25.0, "%.1f")
                    
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
