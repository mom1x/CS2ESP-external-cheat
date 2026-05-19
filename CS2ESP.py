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

# Константы для оверлея
WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080

def get_offsets():
    # Загружаем оффсеты (автоматически или из сети)
    return requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json').json(), \
           requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json').json()

offsets, client_dll = get_offsets()

# Основные адреса
dwEntityList = offsets['client.dll']['dwEntityList']
dwLocalPlayerPawn = offsets['client.dll']['dwLocalPlayerPawn']
dwViewMatrix = offsets['client.dll']['dwViewMatrix']

# Поля сущностей
m_iTeamNum = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iTeamNum']
m_lifeState = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_lifeState']
m_pGameSceneNode = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_pGameSceneNode']
m_modelState = client_dll['client.dll']['classes']['CSkeletonInstance']['fields']['m_modelState']
m_hPlayerPawn = client_dll['client.dll']['classes']['CCSPlayerController']['fields']['m_hPlayerPawn']

# Подключение к процессу (без админа)
def connect_to_game():
    try:
        pm = pymem.Pymem("cs2.exe")
        client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll
        return pm, client
    except:
        return None, None

pm, client = connect_to_game()

def w2s(mtx, pos):
    w = mtx[12]*pos[0] + mtx[13]*pos[1] + mtx[14]*pos[2] + mtx[15]
    if w < 0.01: return None
    x = (mtx[0]*pos[0] + mtx[1]*pos[1] + mtx[2]*pos[2] + mtx[3]) / w
    y = (mtx[4]*pos[0] + mtx[5]*pos[1] + mtx[6]*pos[2] + mtx[7]) / w
    return [WINDOW_WIDTH/2 + (WINDOW_WIDTH/2 * x), WINDOW_HEIGHT/2 - (WINDOW_HEIGHT/2 * y)]

def draw_esp(draw_list):
    if not pm: return
    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i*4) for i in range(16)]
        local_pawn = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_pawn: return
        local_team = pm.read_int(local_pawn + m_iTeamNum)
        
        entity_list = pm.read_longlong(client + dwEntityList)
        
        for i in range(1, 65):
            # Безопасное чтение энтити
            list_entry = pm.read_longlong(entity_list + (8 * (i & 0x7FFF) >> 9) + 16)
            if not list_entry: continue
            controller = pm.read_longlong(list_entry + 120 * (i & 0x1FF))
            if not controller: continue
            
            pawn_handle = pm.read_int(controller + m_hPlayerPawn)
            pawn_list_entry = pm.read_longlong(entity_list + 0x8 * ((pawn_handle & 0x7FFF) >> 9) + 16)
            pawn = pm.read_longlong(pawn_list_entry + 120 * (pawn_handle & 0x1FF))
            
            if not pawn or pawn == local_pawn: continue
            if pm.read_int(pawn + m_lifeState) != 0: continue
            if pm.read_int(pawn + m_iTeamNum) == local_team: continue
            
            scene_node = pm.read_longlong(pawn + m_pGameSceneNode)
            bone_matrix = pm.read_longlong(scene_node + m_modelState + 0x80)
            
            head = [pm.read_float(bone_matrix + 6*32 + j*4) for j in range(3)]
            head[2] += 8
            h_2d = w2s(view_matrix, head)
            
            if h_2d:
                draw_list.add_circle(h_2d[0], h_2d[1], 5, imgui.get_color_u32_rgba(1,0,0,1), thickness=2)
    except: pass

def main():
    if not glfw.init(): return
    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "ESP", None, None)
    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)
    
    hwnd = glfw.get_win32_window(window)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED)
    
    while not glfw.window_should_close(window):
        glfw.poll_events()
        imgui.new_frame()
        imgui.set_next_window_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        imgui.set_next_window_position(0, 0)
        imgui.begin("Overlay", flags=imgui.WINDOW_NO_TITLE_BAR | imgui.WINDOW_NO_BACKGROUND | imgui.WINDOW_NO_RESIZE)
        draw_esp(imgui.get_window_draw_list())
        imgui.end()
        
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        imgui.render()
        impl.render(imgui.get_draw_data())
        glfw.swap_buffers(window)
    impl.shutdown()
    glfw.terminate()

if __name__ == '__main__':
    main()
