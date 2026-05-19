import pymem
import pymem.process
import win32gui, win32con
import time, os, sys
import imgui
from imgui.integrations.glfw import GlfwRenderer
import glfw
import OpenGL.GL as gl
import requests
import json

WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080

print("[ * ] Запуск инициализации оверлея...")

exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
local_offsets_path = os.path.join(exe_dir, 'offsets', 'offsets.json')
local_client_path = os.path.join(exe_dir, 'offsets', 'client_dll.json')

try:
    if os.path.exists(local_offsets_path) and os.path.exists(local_client_path):
        with open(local_offsets_path, 'r', encoding='utf-8') as f:
            offsets = json.load(f)
        with open(local_client_path, 'r', encoding='utf-8') as f:
            client_dll = json.load(f)
        print("[ + ] Оффсеты успешно загружены из ВНЕШНЕЙ папки offsets!")
    else:
        print("[ * ] Внешняя папка offsets не найдена. Загружаем оригинальные ссылки...")
        offsets = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json').json()
        client_dll = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json').json()
        print("[ + ] Оффсеты успешно получены из сети.")
except Exception as e:
    print(f"[ ! ] Ошибка при чтении файлов: {e}. Применяются резервные интернет-ссылки.")
    offsets = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json').json()
    client_dll = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json').json()

# Инициализация смещений
dwEntityList = offsets['client.dll']['dwEntityList']
dwLocalPlayerPawn = offsets['client.dll']['dwLocalPlayerPawn']
dwViewMatrix = offsets['client.dll']['dwViewMatrix']

m_iTeamNum = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iTeamNum']
m_lifeState = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_lifeState']
m_pGameSceneNode = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_pGameSceneNode']
m_modelState = client_dll['client.dll']['classes']['CSkeletonInstance']['fields']['m_modelState']
m_hPlayerPawn = client_dll['client.dll']['classes']['CCSPlayerController']['fields']['m_hPlayerPawn']
m_iHealth = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iHealth']

print("[ * ] Ожидание запуска процесса cs2.exe...")
while True:
    time.sleep(1)
    try:
        pm = pymem.Pymem("cs2.exe")
        client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
        break
    except:
        pass

print("[ + ] Процесс cs2.exe успешно обнаружен!")
time.sleep(1)
os.system("cls")

def w2s(mtx, posx, posy, posz, width, height):
    screenW = mtx[12]*posx + mtx[13]*posy + mtx[14]*posz + mtx[15]
    if screenW > 0.001:
        screenX = mtx[0]*posx + mtx[1]*posy + mtx[2]*posz + mtx[3]
        screenY = mtx[4]*posx + mtx[5]*posy + mtx[6]*posz + mtx[7]
        camX = width / 2
        camY = height / 2
        x = camX + (camX * screenX / screenW) // 1
        y = camY - (camY * screenY / screenW) // 1
        return [x, y]
    return [-999, -999]

def esp(draw_list):
    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i * 4) for i in range(16)]
        local_player = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_player: 
            return
        
        try:
            local_team = pm.read_int(local_player + m_iTeamNum)
        except:
            return

        entity_list = pm.read_longlong(client + dwEntityList)
        if not entity_list:
            return

        # Перебор 64 слотов игроков на сервере
        for i in range(1, 65):
            try:
                # Получаем entry для контроллера
                list_entry = pm.read_longlong(entity_list + (8 * (i & 0x7FFF) >> 9) + 16)
                if not list_entry: 
                    continue

                entity_controller = pm.read_longlong(list_entry + 120 * (i & 0x1FF))
                if not entity_controller: 
                    continue

                # Получаем хэндл пешки игрока из контроллера
                entity_controller_pawn = pm.read_longlong(entity_controller + m_hPlayerPawn)
                if not entity_controller_pawn: 
                    continue

                # Смещаемся к entry самой пешки персонажа
                pawn_list_entry = pm.read_longlong(entity_list + (8 * ((entity_controller_pawn & 0x7FFF) >> 9) + 16))
                if not pawn_list_entry: 
                    continue

                entity_pawn = pm.read_longlong(pawn_list_entry + 120 * (entity_controller_pawn & 0x1FF))
                if not entity_pawn or entity_pawn == local_player: 
                    continue

                # Проверка здоровья
                entity_hp = pm.read_int(entity_pawn + m_iHealth)
                if entity_hp <= 0 or entity_hp > 100:
                    continue

                # Проверка команды (отсекаем союзников)
                entity_team = pm.read_int(entity_pawn + m_iTeamNum)
                if entity_team == local_team:
                    continue

                # Скелет и узлы сцены
                game_scene = pm.read_longlong(entity_pawn + m_pGameSceneNode)
                if not game_scene: 
                    continue
                
                bone_matrix = pm.read_longlong(game_scene + m_modelState + 0x80)
                if not bone_matrix: 
                    continue

                # 3D координаты позиции головы (Bone ID: 6)
                headX = pm.read_float(bone_matrix + 6 * 0x20)
                headY = pm.read_float(bone_matrix + 6 * 0x20 + 0x4)
                headZ = pm.read_float(bone_matrix + 6 * 0x20 + 0x8) + 8
                head_pos = w2s(view_matrix, headX, headY, headZ, WINDOW_WIDTH, WINDOW_HEIGHT)

                # 3D координаты ног (Bone ID: 28)
                legZ = pm.read_float(bone_matrix + 28 * 0x20 + 0x8)
                leg_pos = w2s(view_matrix, headX, headY, legZ, WINDOW_WIDTH, WINDOW_HEIGHT)

                if head_pos[0] == -999 or leg_pos[0] == -999: 
                    continue

                # Расчет геометрии 2D бокса
                delta = abs(head_pos[1] - leg_pos[1])
                leftX = head_pos[0] - delta // 3
                rightX = head_pos[0] + delta // 3

                # Отрисовка
                color = imgui.get_color_u32_rgba(1.0, 0.0, 0.0, 1.0) # Красный цвет для врагов
                draw_list.add_line(leftX, leg_pos[1], rightX, leg_pos[1], color, 1.5)
                draw_list.add_line(leftX, leg_pos[1], leftX, head_pos[1], color, 1.5)
                draw_list.add_line(rightX, leg_pos[1], rightX, head_pos[1], color, 1.5)
                draw_list.add_line(leftX, head_pos[1], rightX, head_pos[1], color, 1.5)

                # Отображение HP рядышком с боксом
                draw_list.add_text(leftX - 25, head_pos[1] - 5, color, f"{entity_hp} HP")

            except:
                continue
    except:
        pass

def main():
    if not glfw.init(): 
        return
    glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
    glfw.window_hint(glfw.FLOATING, glfw.TRUE)
    glfw.window_hint(glfw.RESIZABLE, glfw.FALSE)
    
    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "Overlay Space", None, None)
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
                          win32con.SWP_NOACTIVATE)

    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)

    print("[ + ] Наложение отрисовано. Оверлей активен.")

    while not glfw.window_should_close(window):
        glfw.poll_events()
        impl.process_inputs()
        imgui.new_frame()

        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("ESP_Overlay", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_RESIZE | imgui.WINDOW_NO_SCROLLBAR | imgui.WINDOW_NO_COLLAPSE | imgui.WINDOW_NO_BACKGROUND)

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
