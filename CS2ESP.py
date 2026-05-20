import pymem
import pymem.process
import win32gui, win32con
import time, os, json
import imgui
from imgui.integrations.glfw import GlfwRenderer
import glfw
import OpenGL.GL as gl

WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080

# Загрузка оффсетов из локальной папки
try:
    with open("offsets/offsets.json", "r", encoding="utf-8") as f:
        offsets = json.load(f)
    with open("offsets/client_dll.json", "r", encoding="utf-8") as f:
        client_dll = json.load(f)
except FileNotFoundError:
    # Фолбэк на случай если запустили без папки
    import requests
    offsets = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json').json()
    client_dll = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json').json()

dwEntityList = offsets['client.dll']['dwEntityList']
dwLocalPlayerPawn = offsets['client.dll']['dwLocalPlayerPawn']
dwViewMatrix = offsets['client.dll']['dwViewMatrix']

m_iTeamNum = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iTeamNum']
m_lifeState = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_lifeState']
m_pGameSceneNode = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_pGameSceneNode']
m_modelState = client_dll['client.dll']['classes']['CSkeletonInstance']['fields']['m_modelState']
m_hPlayerPawn = client_dll['client.dll']['classes']['CCSPlayerController']['fields']['m_hPlayerPawn']
m_iHealth = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iHealth']
m_vOldOrigin = client_dll['client.dll']['classes']['C_BasePlayerPawn']['fields']['m_vOldOrigin']

print("Ожидание запуска cs2.exe...")
while True:
    time.sleep(1)
    try:
        pm = pymem.Pymem("cs2.exe")
        client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
        break
    except:
        pass

def w2s(mtx, posx, posy, posz, width, height):
    screenW = mtx[12]*posx + mtx[13]*posy + mtx[14]*posz + mtx[15]
    if screenW > 0.001:
        screenX = mtx[0]*posx + mtx[1]*posy + mtx[2]*posz + mtx[3]
        screenY = mtx[4]*posx + mtx[5]*posy + mtx[6]*posz + mtx[7]
        camX = width / 2
        camY = height / 2
        x = camX + (camX * screenX / screenW)
        y = camY - (camY * screenY / screenW)
        return [int(x), int(y)]
    return [-999, -999]

def esp(draw_list):
    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
        local_player = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_player: return
        local_team = pm.read_int(local_player + m_iTeamNum)
    except:
        return

    entity_list = pm.read_longlong(client + dwEntityList)
    if not entity_list: return

    for i in range(64):
        try:
            list_entry = pm.read_longlong(entity_list + ((8 * (i & 0x7FFF) >> 9) + 16))
            if not list_entry: continue

            entity_controller = pm.read_longlong(list_entry + 120 * (i & 0x1FF))
            if not entity_controller: continue

            entity_controller_pawn = pm.read_longlong(entity_controller + m_hPlayerPawn)
            if not entity_controller_pawn: continue

            list_entry2 = pm.read_longlong(entity_list + (0x8 * ((entity_controller_pawn & 0x7FFF) >> 9) + 16))
            if not list_entry2: continue

            entity_pawn = pm.read_longlong(list_entry2 + 120 * (entity_controller_pawn & 0x1FF))
            if not entity_pawn or entity_pawn == local_player: continue

            if pm.read_int(entity_pawn + m_lifeState) != 256: continue
            if pm.read_int(entity_pawn + m_iTeamNum) == local_team: continue

            # Получение координат
            game_scene = pm.read_longlong(entity_pawn + m_pGameSceneNode)
            bone_matrix = pm.read_longlong(game_scene + m_modelState + 0x80)

            # Позиция ног (Origin)
            pos_x = pm.read_float(entity_pawn + m_vOldOrigin)
            pos_y = pm.read_float(entity_pawn + m_vOldOrigin + 4)
            pos_z = pm.read_float(entity_pawn + m_vOldOrigin + 8)

            # Позиция головы из кости 6
            head_x = pm.read_float(bone_matrix + 6 * 0x20)
            head_y = pm.read_float(bone_matrix + 6 * 0x20 + 0x4)
            head_z = pm.read_float(bone_matrix + 6 * 0x20 + 0x8)

            screen_head = w2s(view_matrix, head_x, head_y, head_z + 11.0, WINDOW_WIDTH, WINDOW_HEIGHT)
            screen_legs = w2s(view_matrix, pos_x, pos_y, pos_z, WINDOW_WIDTH, WINDOW_HEIGHT)

            if screen_head[0] == -999 or screen_legs[0] == -999: continue

            # Расчет размеров бокса
            height = abs(screen_head[1] - screen_legs[1])
            width = height / 2
            
            left_x = screen_head[0] - width / 2
            right_x = screen_head[0] + width / 2

            color = imgui.get_color_u32_rgba(1.0, 0.0, 0.0, 1.0) # Красный
            
            # Отрисовка рамки прямоугольника
            draw_list.add_rect(left_x, screen_head[1], right_x, screen_legs[1], color, 0.0, 15, 2.0)

            # Вывод здоровья
            entity_hp = pm.read_int(entity_pawn + m_iHealth)
            draw_list.add_text(left_x - 25, screen_head[1] - 5, color, f"{entity_hp} HP")
        except:
            continue

def main():
    if not glfw.init(): return
    
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    glfw.window_hint(glfw.DECORATED, glfw.FALSE)

    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "Overlay", None, None)
    if not window:
        glfw.terminate()
        return

    hwnd = glfw.get_win32_window(window)
    
    # Настройка прозрачности через WinAPI клика сквозь окно
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    style &= ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME | win32con.WS_MINIMIZEBOX | win32con.WS_MAXIMIZEBOX)
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    ex_style |= win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, WINDOW_WIDTH, WINDOW_HEIGHT, win32con.SWP_NOACTIVATE)

    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()

        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("Canvas", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_SCROLLBAR | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_INPUTS)

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
