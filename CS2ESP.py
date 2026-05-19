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

# --- ПОДГОТОВКА ОФФСЕТОВ ---
def get_offsets():
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    off_path = os.path.join(exe_dir, 'offsets', 'offsets.json')
    cli_path = os.path.join(exe_dir, 'offsets', 'client_dll.json')
    
    if os.path.exists(off_path) and os.path.exists(cli_path):
        with open(off_path, 'r', encoding='utf-8') as f: offsets = json.load(f)
        with open(cli_path, 'r', encoding='utf-8') as f: client_dll = json.load(f)
        print("[+] Загружено из папки offsets")
    else:
        offsets = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/offsets.json').json()
        client_dll = requests.get('https://raw.githubusercontent.com/a2x/cs2-dumper/main/output/client_dll.json').json()
        print("[+] Загружено из интернета")
    return offsets, client_dll

offsets, client_dll = get_offsets()

dwEntityList = offsets['client.dll']['dwEntityList']
dwLocalPlayerPawn = offsets['client.dll']['dwLocalPlayerPawn']
dwViewMatrix = offsets['client.dll']['dwViewMatrix']

m_iTeamNum = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iTeamNum']
m_lifeState = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_lifeState']
m_pGameSceneNode = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_pGameSceneNode']
m_modelState = client_dll['client.dll']['classes']['CSkeletonInstance']['fields']['m_modelState']
m_hPlayerPawn = client_dll['client.dll']['classes']['CCSPlayerController']['fields']['m_hPlayerPawn']
m_iHealth = client_dll['client.dll']['classes']['C_BaseEntity']['fields']['m_iHealth']

pm = pymem.Pymem("cs2.exe")
client = pymem.process.module_from_name(pm.process_handle, "client.dll").lpBaseOfDll

# --- ФУНКЦИИ ---
def w2s(mtx, pos):
    w = mtx[12]*pos[0] + mtx[13]*pos[1] + mtx[14]*pos[2] + mtx[15]
    if w < 0.01: return None
    x = (mtx[0]*pos[0] + mtx[1]*pos[1] + mtx[2]*pos[2] + mtx[3]) / w
    y = (mtx[4]*pos[0] + mtx[5]*pos[1] + mtx[6]*pos[2] + mtx[7]) / w
    return [WINDOW_WIDTH/2 + (WINDOW_WIDTH/2 * x), WINDOW_HEIGHT/2 - (WINDOW_HEIGHT/2 * y)]

def draw_esp(draw_list):
    try:
        view_matrix = [pm.read_float(client + dwViewMatrix + i*4) for i in range(16)]
        local_pawn = pm.read_longlong(client + dwLocalPlayerPawn)
        if not local_pawn: return
        local_team = pm.read_int(local_pawn + m_iTeamNum)
        entity_list = pm.read_longlong(client + dwEntityList)
        
        for i in range(1, 65):
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
            leg = [head[0], head[1], pm.read_float(bone_matrix + 28*32 + 8) - 10]
            
            h_2d, l_2d = w2s(view_matrix, head), w2s(view_matrix, leg)
            if h_2d and l_2d:
                h = abs(h_2d[1] - l_2d[1])
                draw_list.add_rect(h_2d[0]-h/4, h_2d[1], h_2d[0]+h/4, l_2d[1], imgui.get_color_u32_rgba(1,0,0,1), thickness=2)
    except: pass

# --- MAIN ОВЕРЛЕЙ ---
def main():
    glfw.init()
    window = glfw.create_window(WINDOW_WIDTH, WINDOW_HEIGHT, "Overlay", None, None)
    glfw.make_context_current(window)
    imgui.create_context()
    impl = GlfwRenderer(window)
    
    hwnd = glfw.get_win32_window(window)
    win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED)
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, win32con.SWP_NOSIZE | win32con.SWP_NOMOVE)
    
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
