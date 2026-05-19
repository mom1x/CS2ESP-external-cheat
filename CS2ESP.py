import pymem
import pymem.process
import win32gui, win32con
import time, os
import imgui
from imgui.integrations.glfw import GlfwRenderer
import glfw
import OpenGL.GL as gl
import requests
import ctypes
import sys

WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080

# Принудительная проверка прав администратора при запуске в коде
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    # Запрашиваем повышение прав у Windows
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    sys.exit()

# Безопасное получение оффсетов
try:
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
except Exception as e:
    print(f"Ошибка загрузки оффсетов: {e}")
    time.sleep(5)
    sys.exit()

# Ожидаем запуска cs2.exe
while True:
    time.sleep(1)
    try:
        pm = pymem.Pymem("cs2.exe")
        client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
        break
    except:
        pass

def w2s(mtx, posx, posy, posz, width, height):
    try:
        screenW = mtx[12]*posx + mtx[13]*posy + mtx[14]*posz + mtx[15]
        if screenW > 0.001:
            screenX = mtx[0]*posx + mtx[1]*posy + mtx[2]*posz + mtx[3]
            screenY = mtx[4]*posx + mtx[5]*posy + mtx[6]*posz + mtx[7]
            camX = width / 2
            camY = height / 2
            x = camX + (camX * screenX / screenW) // 1
            y = camY - (camY * screenY / screenW) // 1
            return [x, y]
    except:
        pass
    return [-999, -999]

def esp(draw_list):
    # Защищаем базовое чтение локального игрока
    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
        local_player = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_player:
            return
        local_team = pm.read_int(local_player + m_iTeamNum)
    except:
        return

    # Защищаем весь цикл перебора сущностей — теперь падений не будет!
    for i in range(64):
        try:
            entity = pm.read_longlong(client + dwEntityList)
            if not entity:
                continue

            list_entry = pm.read_longlong(entity + ((8 * (i & 0x7FFF) >> 9) + 16))
            if not list_entry:
                continue

            entity_controller = pm.read_longlong(list_entry + (120) * (i & 0x1FF))
            if not entity_controller:
                continue

            entity_controller_pawn = pm.read_longlong(entity_controller + m_hPlayerPawn)
            if not entity_controller_pawn:
                continue

            list_entry = pm.read_longlong(entity + (0x8 * ((entity_controller_pawn & 0x7FFF) >> 9) + 16))
            if not list_entry:
                continue

            entity_pawn = pm.read_longlong(list_entry + (120) * (entity_controller_pawn & 0x1FF))
            if not entity_pawn or entity_pawn == local_player:
                continue

            if pm.read_int(entity_pawn + m_lifeState) != 256:
                continue

            if pm.read_int(entity_pawn + m_iTeamNum) == local_team:
                continue

            color = imgui.get_color_u32_rgba(1, 0, 0, 1)

            game_scene = pm.read_longlong(entity_pawn + m_pGameSceneNode)
            if not game_scene:
                continue
                
            bone_matrix = pm.read_longlong(game_scene + m_modelState + 0x80)
            if not bone_matrix:
                continue

            headX = pm.read_float(bone_matrix + 6 * 0x20)
            headY = pm.read_float(bone_matrix + 6 * 0x20 + 0x4)
            headZ = pm.read_float(bone_matrix + 6 * 0x20 + 0x8) + 8
            head_pos = w2s(view_matrix, headX, headY, headZ, WINDOW_WIDTH, WINDOW_HEIGHT)

            legZ = pm.read_float(bone_matrix + 28 * 0x20 + 0x8)
            leg_pos = w2s(view_matrix, headX, headY, legZ, WINDOW_WIDTH, WINDOW_HEIGHT)

            if head_pos[0] == -999 or leg_pos[0] == -999:
                continue

            delta = abs(head_pos[1] - leg_pos[1])
            leftX = head_pos[0] - delta // 3
            rightX = head_pos[0] + delta // 3

            draw_list.add_line(leftX, leg_pos[1], rightX, leg_pos[1], color, 2.0)
            draw_list.add_line(leftX, leg_pos[1], leftX, head_pos[1], color, 2.0)
            draw_list.add_line(rightX, leg_pos[1], rightX, head_pos[1], color, 2.0)
            draw_list.add_line(leftX, head_pos[1], rightX, head_pos[1], color, 2.0)

            entity_hp = pm.read_int(entity_pawn + m_iHealth)
            draw_list.add_text(leftX - 25, head_pos[1] - 5, color, str(entity_hp))
        except:
            # Если адрес памяти недоступен — просто пропускаем итерацию, не ломая оверлей
            continue

def main():
    glfw.init()
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "overlay", None, None)

    hwnd = glfw.get_win32_window(window)
    style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    style &= ~(win32con.WS_CAPTION | win32con.WS_THICKFRAME)
    win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
    ex_style = win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, -2, -2, 0, 0,
                          win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE)

    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()

        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("overlay",
                    flags=imgui.WINDOW_NO_TITLE_BAR |
                          imgui.WINDOW_NO_RESIZE |
                          imgui.WINDOW_NO_SCROLLBAR |
                          imgui.WINDOW_NO_COLLAPSE |
                          imgui.WINDOW_NO_BACKGROUND)

        draw_list = imgui.get_window_draw_list()
        
        # Безопасный вызов отрисовки
        try:
            esp(draw_list)
        except:
            pass

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
