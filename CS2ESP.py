import pymem
import pymem.process
import win32gui, win32con, win32api
import time, os, sys, json, requests
import imgui
from imgui.integrations.glfw import GlfwRenderer
import glfw
import OpenGL.GL as gl

# Настройка размеров экрана под твой монитор автоматически
WINDOW_WIDTH = win32api.GetSystemMetrics(0)
WINDOW_HEIGHT = win32api.GetSystemMetrics(1)

debug_info = {"status": "Инициализация...", "entities_found": 0, "local_pawn": 0}

def get_resource_path(relative_path):
    """ Получает путь к ресурсам, упакованным через PyInstaller """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

def load_offsets():
    """ Загружает оффсеты из локальных файлов или из сети в случае их отсутствия """
    local_offsets_path = get_resource_path("offsets/offsets.json")
    local_client_path = get_resource_path("offsets/client_dll.json")
    
    if os.path.exists(local_offsets_path) and os.path.exists(local_client_path):
        try:
            print("[INFO] Загрузка встроенных оффсетов из памяти EXE...")
            with open(local_offsets_path, 'r') as f:
                off = json.load(f)
            with open(local_client_path, 'r') as f:
                cl = json.load(f)
            return off, cl
        except Exception as e:
            print(f"[WARN] Ошибка чтения локальных файлов, пробуем сеть: {e}")

    try:
        print("[INFO] Локальные оффсеты не найдены. Загрузка из сети...")
        off = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json').json()
        cl = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json').json()
        return off, cl
    except Exception as e:
        print(f"[CRIT] Ошибка сети. Не удалось получить данные: {e}")
        return None, None

off_data, client_data = load_offsets()
if not off_data or not client_data:
    print("[ERROR] Не удалось инициализировать базу данных смещений. Завершение работы.")
    sys.exit(1)

# Парсинг необходимых оффсетов
dwEntityList = off_data['client.dll']['dwEntityList']
dwLocalPlayerPawn = off_data['client.dll']['dwLocalPlayerPawn']
dwViewMatrix = off_data['client.dll']['dwViewMatrix']

m_iTeamNum = client_data['client.dll']['classes']['C_BaseEntity']['fields']['m_iTeamNum']
m_iHealth = client_data['client.dll']['classes']['C_BaseEntity']['fields']['m_iHealth']
m_hPlayerPawn = client_data['client.dll']['classes']['CCSPlayerController']['fields']['m_hPlayerPawn']
m_pGameSceneNode = client_data['client.dll']['classes']['C_BaseEntity']['fields']['m_pGameSceneNode']
m_vecAbsOrigin = client_data['client.dll']['classes']['CGameSceneNode']['fields']['m_vecAbsOrigin']
m_lifeState = client_data['client.dll']['classes']['C_BaseEntity']['fields']['m_lifeState']

def w2s(mtx, pos, width, height):
    """ Перевод 3D координат игры в 2D координаты экрана """
    w = mtx[12]*pos[0] + mtx[13]*pos[1] + mtx[14]*pos[2] + mtx[15]
    if w < 0.01: 
        return None
    
    x = mtx[0]*pos[0] + mtx[1]*pos[1] + mtx[2]*pos[2] + mtx[3]
    y = mtx[4]*pos[0] + mtx[5]*pos[1] + mtx[6]*pos[2] + mtx[7]
    
    nx = (width / 2) + (x / w) * (width / 2)
    ny = (height / 2) - (y / w) * (height / 2)
    return [nx, ny]

def main_logic(draw_list, pm, client_base):
    try:
        v_matrix = [pm.read_float(client_base + dwViewMatrix + i * 4) for i in range(16)]
        local_pawn = pm.read_longlong(client_base + dwLocalPlayerPawn)
        if not local_pawn: 
            return
        
        local_team = pm.read_int(local_pawn + m_iTeamNum)
        ent_list = pm.read_longlong(client_base + dwEntityList)
        
        debug_info["local_pawn"] = local_pawn
        count = 0

        for i in range(1, 64):
            # Поиск Контроллера сущности
            entry_ptr = pm.read_longlong(ent_list + 8 * ((i & 0x7FFF) >> 9) + 16)
            if not entry_ptr: 
                continue
            
            controller = pm.read_longlong(entry_ptr + 120 * (i & 0x1FF))
            if not controller: 
                continue
            
            # Поиск Хэндла связанного Pawn
            pawn_handle = pm.read_int(controller + m_hPlayerPawn)
            if not pawn_handle: 
                continue
            
            # Поиск указателя на сам Pawn
            pawn_ptr = pm.read_longlong(ent_list + 8 * ((pawn_handle & 0x7FFF) >> 9) + 16)
            if not pawn_ptr: 
                continue
            
            pawn = pm.read_longlong(pawn_ptr + 120 * (pawn_handle & 0x1FF))
            if not pawn or pawn == local_pawn: 
                continue

            # Фильтрация состояния игрока/бота
            health = pm.read_int(pawn + m_iHealth)
            team = pm.read_int(pawn + m_iTeamNum)
            life_state = pm.read_int(pawn + m_lifeState)
            
            if health <= 0 or health > 100 or team == local_team or life_state != 0:
                continue

            # Сбор пространственных координат
            scene_node = pm.read_longlong(pawn + m_pGameSceneNode)
            abs_origin = [
                pm.read_float(scene_node + m_vecAbsOrigin),
                pm.read_float(scene_node + m_vecAbsOrigin + 4),
                pm.read_float(scene_node + m_vecAbsOrigin + 8)
            ]
            
            feet = w2s(v_matrix, abs_origin, WINDOW_WIDTH, WINDOW_HEIGHT)
            head = w2s(v_matrix, [abs_origin[0], abs_origin[1], abs_origin[2] + 72], WINDOW_WIDTH, WINDOW_HEIGHT)
            
            if feet and head:
                h = abs(feet[1] - head[1])
                w = h / 2
                
                # Рендеринг интерфейса ESP
                color = imgui.get_color_u32_rgba(1.0, 0.2, 0.2, 1.0)
                draw_list.add_rect(head[0] - w/2, head[1], head[0] + w/2, feet[1], color, thickness=1.5)
                draw_list.add_text(head[0] - w/2, head[1] - 15, color, f"{health} HP")
                count += 1
        
        debug_info["entities_found"] = count

    except Exception as e:
        debug_info["status"] = f"Ошибка чтения: {e}"

def main():
    if not glfw.init(): 
        return
    
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)
    
    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "CS2 Overlay", None, None)
    glfw.make_context_current(window)
    
    hwnd = glfw.get_win32_window(window)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, 
                           win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE) | win32con.WS_EX_LAYERED | win32con.WS_EX_TRANSPARENT)
    
    imgui.create_context()
    impl = GlfwRenderer(window)
    
    pm = None
    client_base = None

    print("[INFO] Скрипт запущен. Ожидание CS2...")

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()
        
        if not pm:
            try:
                pm = pymem.Pymem("cs2.exe")
                client_base = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
                debug_info["status"] = "CS2 найдена и подключена"
                print("[SUCCESS] Успешное подключение к памяти CS2.")
            except:
                debug_info["status"] = "Ожидание запуска cs2.exe..."

        imgui.set_next_window_position(0, 0)
        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.begin("Overlay", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)
        
        draw_list = imgui.get_window_draw_list()
        
        # Вывод системных данных в левый верхний угол экрана
        draw_list.add_text(15, 15, imgui.get_color_u32_rgba(0.0, 1.0, 0.0, 1.0), 
                           f"Статус: {debug_info['status']} | Отрисовано целей: {debug_info['entities_found']}")
        
        if pm and client_base:
            main_logic(draw_list, pm, client_base)
            
        imgui.end()
        imgui.render()
        
        gl.glClearColor(0, 0, 0, 0)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        impl.render(imgui.get_draw_data())
        glfw.swap_buffers(window)
        
    glfw.terminate()

if __name__ == "__main__":
    main()
