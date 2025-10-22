# Virtual WiiMote — DSU server (Cemuhook) + DearPyGui

import socket, struct, time, random, zlib, select, threading, json, os
from collections import deque
from ctypes import windll, byref, Structure
from ctypes import wintypes

import dearpygui.dearpygui as dpg

# ------------------------------ CONFIG & CONSTANTS ------------------------------

APP_TITLE = "Virtual WiiMote"
CONFIG_FILE = "dsu_gui_config.json"

HOST = "127.0.0.1"
PORT = 26761

POINTER_SOURCES = ["mouse", "xinput_rs", "xinput_ls"]

DEFAULTS = {
    "hz": 200,
    "tpad_w": 1920, "tpad_h": 942,
    "invert_y": False,
    "smooth": 0.30,

    # Stick-driven pointer
    "pointer_source": "mouse",            # mouse | xinput_rs | xinput_ls
    "cursor_speed_px_s": 1600.0,          # px/sec at full deflection
    "stick_deadzone": 8000,               # 0..32767

    # Spins/pulses (shake)
    "twirl_z_dps": 800.0,                 # W — spin around Z (twirl)
    "spin_x_dps":  800.0,                 # E — spin around X
    "w_pulse_ax": 38.0,
    "e_pulse_ay": 40.0,
    "pulse_az":   36.0,
    "pulse_ms":   64,
    "cooldown_ms": 20,

    # NEW: Twist (gyro-only) speed while holding twist keys
    "twist_dps":   180.0,                 # deg/s applied when holding front/back/left/right twist

    # Synthetic LS magnitude for D-Pad mapping
    "lstick_magnitude": 255,

    # UI helpers (not saved to bindings-only files)
    "bindings_filename": "bindings_user.json",
}

# Binding types
BIND_VK   = "VK"
BIND_XBTN = "XBTN"

# Default bindings (Wiimote-style + Twist)
# NOTE: VK codes: ';' is VK_OEM_1 (0xBA) on most US layouts.
DEFAULT_BINDINGS = {
    # Wiimote
    "wm_a":           (BIND_VK, ord('A')),
    "wm_b":           (BIND_VK, ord('S')),
    "wm_1":           (BIND_VK, ord('1')),
    "wm_2":           (BIND_VK, ord('2')),
    "wm_plus":        (BIND_VK, 0xBB),        # OEM_PLUS '+'
    "wm_minus":       (BIND_VK, 0xBD),        # OEM_MINUS '-'
    "wm_home":        (BIND_VK, 0x24),        # HOME
    "wm_dpad_left":   (BIND_VK, 0x25),
    "wm_dpad_right":  (BIND_VK, 0x27),
    "wm_dpad_up":     (BIND_VK, 0x26),
    "wm_dpad_down":   (BIND_VK, 0x28),

    # Extra shake/toggle
    "spin_w":         (BIND_VK, ord('W')),
    "spin_e":         (BIND_VK, ord('E')),
    "toggle_off":     (BIND_VK, 0x77),        # F8

    # NEW: Twist (Front/Back/Left/Right)
    "mv_front":       (BIND_VK, ord('O')),    # pitch forward
    "mv_back":        (BIND_VK, ord('L')),    # pitch backward
    "mv_left":        (BIND_VK, ord('K')),    # roll left
    "mv_right":       (BIND_VK, 0xBA),        # roll right (';')
}

# Wiimote actions (for tables)
ACTIONS_WIIMOTE = [
    ("wm_a",           "Wiimote A"),
    ("wm_b",           "Wiimote B (Trigger)"),
    ("wm_1",           "Wiimote 1"),
    ("wm_2",           "Wiimote 2"),
    ("wm_plus",        "Wiimote +"),
    ("wm_minus",       "Wiimote −"),
    ("wm_home",        "Wiimote Home"),
    ("wm_dpad_left",   "Wiimote D-Pad LEFT"),
    ("wm_dpad_right",  "Wiimote D-Pad RIGHT"),
    ("wm_dpad_up",     "Wiimote D-Pad UP"),
    ("wm_dpad_down",   "Wiimote D-Pad DOWN"),
]
ACTIONS_EXTRA = [
    ("spin_w",         "Shake/Twirl Z (W)"),
    ("spin_e",         "Shake/Spin  X (E)"),
    ("toggle_off",     "Toggle Offscreen"),
]
# NEW: Twist bindings (independent of D-Pad; these drive gyro only)
ACTIONS_TWIST = [
    ("mv_front",       "Twist Front (pitch forward)"),
    ("mv_back",        "Twist Back (pitch backward)"),
    ("mv_left",        "Twist Left (roll left)"),
    ("mv_right",       "Twist Right (roll right)"),
]

# ------------------------------ Win32 / XInput ------------------------------

user32 = windll.user32
winmm  = windll.winmm
GetAsyncKeyState = user32.GetAsyncKeyState

# VK names table (partial)
VK_NAME = {
    0x24:"HOME", 0x25:"LEFT", 0x26:"UP", 0x27:"RIGHT", 0x28:"DOWN",
    0x20:"SPACE", 0x09:"TAB", 0x1B:"ESC", 0x0D:"ENTER",
    0xA0:"LSHIFT", 0xA2:"LCTRL", 0xA4:"LALT",
    0x70:"F1",0x71:"F2",0x72:"F3",0x73:"F4",0x74:"F5",0x75:"F6",
    0x76:"F7",0x77:"F8",0x78:"F9",0x79:"F10",0x7A:"F11",0x7B:"F12",
    0xBB:"OEM_PLUS(+)", 0xBD:"OEM_MINUS(-)",
    0xBA:"OEM_1(;)",    # shows as ';' on US layout
}
for c in range(ord('0'), ord('9')+1):
    VK_NAME[c] = chr(c)
for c in range(ord('A'), ord('Z')+1):
    VK_NAME[c] = chr(c)

def vk_to_name(code:int)->str:
    return VK_NAME.get(code, f"VK_{code}")

# XInput
try:
    _xinput = windll.xinput1_4
except OSError:
    try:
        _xinput = windll.xinput1_3
    except OSError:
        _xinput = None

class XINPUT_GAMEPAD(Structure):
    _fields_ = [("wButtons", wintypes.WORD),
                ("bLeftTrigger", wintypes.BYTE),
                ("bRightTrigger", wintypes.BYTE),
                ("sThumbLX", wintypes.SHORT),
                ("sThumbLY", wintypes.SHORT),
                ("sThumbRX", wintypes.SHORT),
                ("sThumbRY", wintypes.SHORT)]

class XINPUT_STATE(Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD),
                ("Gamepad", XINPUT_GAMEPAD)]

XBTN = {
    "DPAD_UP":0x0001, "DPAD_DOWN":0x0002, "DPAD_LEFT":0x0004, "DPAD_RIGHT":0x0008,
    "START":0x0010, "BACK":0x0020, "LS":0x0040, "RS":0x0080,
    "LB":0x0100, "RB":0x0200, "A":0x1000, "B":0x2000, "X":0x4000, "Y":0x8000
}
XBTN_NAME = {v:k for k,v in XBTN.items()}

def xinput_get_state(idx=0):
    if not _xinput: return None
    st = XINPUT_STATE()
    res = _xinput.XInputGetState(idx, byref(st))
    if res != 0: return None
    return st

# DS4 (DSU) bits
BTN_L1=0x01; BTN_R1=0x02; BTN_L2=0x04; BTN_R2=0x08
BTN_SQUARE=0x10; BTN_CROSS=0x20; BTN_CIRCLE=0x40; BTN_TRIANGLE=0x80
PS_BTN=0x01; TOUCH_BTN=0x02; SHARE_BTN=0x10; OPTIONS_BTN=0x20

SM_CXSCREEN, SM_CYSCREEN = 0, 1

class POINT(Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

def screen_size():
    return user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)

def mouse_pos():
    p = POINT()
    user32.GetCursorPos(byref(p))
    return p.x, p.y

# ------------------------------ LOG ------------------------------

log_queue = deque(maxlen=500)
def log(msg:str):
    ts = time.strftime("%H:%M:%S")
    log_queue.append(f"[{ts}] {msg}")
    print(f"[{APP_TITLE}] {msg}")

# ------------------------------ CONFIG RUNTIME ------------------------------

class Config:
    def __init__(self):
        self.lock = threading.Lock()
        self.values = dict(DEFAULTS)
        self.bindings = dict(DEFAULT_BINDINGS)
        self.rebind_target = None
        self.rebind_deadline = 0.0
        self.want_stop = False
        self.subs_count = 0  # for UI

    def load(self, path=CONFIG_FILE):
        if not os.path.isfile(path): return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self.lock:
                self.values.update(data.get("values", {}))
                loaded = data.get("bindings", {})
                for k,v in loaded.items():
                    if isinstance(v, list) and len(v)==2:
                        self.bindings[k] = (v[0], int(v[1]))
            log("Config loaded.")
        except Exception as e:
            log(f"Error loading config: {e}")

    def save(self, path=CONFIG_FILE):
        try:
            with self.lock:
                data = {"values": self.values, "bindings": self.bindings}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            log("Config saved.")
        except Exception as e:
            log(f"Error saving config: {e}")

    # --- bindings-only save/load ---
    def save_bindings_only(self, path:str):
        try:
            with self.lock:
                data = {"bindings": self.bindings}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            log(f"Bindings saved to '{path}'.")
        except Exception as e:
            log(f"Error saving bindings: {e}")

    def load_bindings_only(self, path:str):
        try:
            if not os.path.isfile(path):
                log(f"Bindings file not found: '{path}'")
                return
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded = data.get("bindings", {})
            with self.lock:
                for k,v in loaded.items():
                    if isinstance(v, list) and len(v)==2:
                        self.bindings[k] = (v[0], int(v[1]))
            log(f"Bindings loaded from '{path}'.")
        except Exception as e:
            log(f"Error loading bindings: {e}")

    # --- reset to defaults (and reset config JSON) ---
    def reset_to_defaults(self, delete_config_file=True):
        with self.lock:
            self.values = dict(DEFAULTS)
            self.bindings = dict(DEFAULT_BINDINGS)
            self.rebind_target = None
            self.rebind_deadline = 0.0
        if delete_config_file and os.path.isfile(CONFIG_FILE):
            try:
                os.remove(CONFIG_FILE)
                log("Deleted existing config file.")
            except Exception as e:
                log(f"Could not delete config file: {e}")
        self.save(CONFIG_FILE)
        log("Reset to defaults completed.")

    def begin_rebind(self, action:str, seconds=5):
        with self.lock:
            self.rebind_target = action
            self.rebind_deadline = time.time() + seconds

    def cancel_rebind(self):
        with self.lock:
            self.rebind_target = None
            self.rebind_deadline = 0.0

config = Config()
config.load()

# ------------------------------ DSU PROTOCOL ------------------------------

PROTOCOL = 1001
MAGIC_S = b"DSUS"
MAGIC_C = b"DSUC"
SLOT = 0
STATE_CONNECTED = 2
MODEL_FULL_GYRO = 2
CONN_BT = 2
MAC = random.randrange(1<<48).to_bytes(6, "big")
BAT_FULL = 0x05
G = 9.81

def frames_for_ms(ms, hz):
    return max(2, int(hz * (ms/1000.0)))

def pack_header(msg_type, payload, server_id=0x12345678):
    base = struct.pack("<4sHHI", MAGIC_S, PROTOCOL, len(payload)+4, 0) + struct.pack("<I", server_id) + struct.pack("<I", msg_type)
    crc = zlib.crc32(base[:8] + b"\x00\x00\x00\x00" + base[12:] + payload) & 0xFFFFFFFF
    return base[:8] + struct.pack("<I", crc) + base[12:] + payload

def resp_version():
    payload = struct.pack("<H", PROTOCOL)
    return pack_header(0x100000, payload)

def common_begin():
    return struct.pack("<BBBB6sB", SLOT, STATE_CONNECTED, MODEL_FULL_GYRO, CONN_BT, MAC, BAT_FULL)

def resp_list_ports():
    payload = common_begin() + b"\x01"
    return pack_header(0x100001, payload)

# ------------------------------ INPUT HELPERS ------------------------------

def binding_name(b):
    if not b: return "-"
    kind, code = b
    if kind == BIND_VK:
        return vk_to_name(code)
    elif kind == BIND_XBTN:
        return XBTN_NAME.get(code, f"XBTN_{code}")
    return "?"

def is_binding_down(b, xinput_state):
    if not b: return False
    kind, code = b
    if kind == BIND_VK:
        return (GetAsyncKeyState(code) & 0x8000) != 0
    elif kind == BIND_XBTN:
        if xinput_state is None: return False
        return (xinput_state.Gamepad.wButtons & code) != 0
    return False

def scan_next_pressed(xinput_state):
    # Keyboard: scan VKs
    for vk in range(0x08, 0xFE):
        try:
            if GetAsyncKeyState(vk) & 0x8000:
                return (BIND_VK, vk)
        except Exception:
            pass
    # XInput buttons
    if xinput_state is not None:
        w = xinput_state.Gamepad.wButtons
        if w:
            for _,mask in XBTN.items():
                if (w & mask): return (BIND_XBTN, mask)
    return None

def norm_axis(v, dz):
    v = int(v)
    dz = max(0, int(dz))
    if abs(v) <= dz: return 0.0
    sign = 1.0 if v > 0 else -1.0
    return sign * (abs(v) - dz) / (32767.0 - dz)

# ------------------------------ SERVER ------------------------------

class State:
    __slots__ = ("idx","tx_prev","ty_prev","offscreen",
                 "prev_w","prev_e","dir_w","dir_e",
                 "w_pulse_left","e_pulse_left","w_cooldown","e_cooldown",
                 "last_toggle_us")
    def __init__(self):
        self.idx = 0
        self.tx_prev = None
        self.ty_prev = None
        self.offscreen = False
        self.prev_w = False
        self.prev_e = False
        self.dir_w = 1.0
        self.dir_e = 1.0
        self.w_pulse_left = 0
        self.e_pulse_left = 0
        self.w_cooldown = 0
        self.e_cooldown = 0
        self.last_toggle_us = 0

def resp_data(st: State):
    with config.lock:
        vals = dict(config.values)
        binds = dict(config.bindings)

    hz = max(1, int(vals["hz"]))
    smooth = float(vals["smooth"])

    st.idx += 1
    xi = xinput_get_state(0)

    # ----- Pointer (touch) -----
    tpad_w = int(vals["tpad_w"]); tpad_h = int(vals["tpad_h"])
    pointer_source = vals.get("pointer_source","mouse")

    if pointer_source == "mouse":
        w, h = screen_size()
        mx, my = mouse_pos()
        if vals["invert_y"]:
            my = h - 1 - my
        tx_raw = int(max(0, min(tpad_w-1, mx * (tpad_w-1) // max(1, w-1))))
        ty_raw = int(max(0, min(tpad_h-1, my * (tpad_h-1) // max(1, h-1))))
    else:
        # Stick-relative pointer
        dz = int(vals["stick_deadzone"])
        spx = float(vals["cursor_speed_px_s"])
        ax_x = 0; ax_y = 0
        if xi is not None:
            if pointer_source == "xinput_rs":
                ax_x = xi.Gamepad.sThumbRX
                ax_y = xi.Gamepad.sThumbRY
            else:
                ax_x = xi.Gamepad.sThumbLX
                ax_y = xi.Gamepad.sThumbLY
        nx = norm_axis(ax_x, dz)
        ny = norm_axis(ax_y, dz)
        if vals["invert_y"]:
            ny = -ny
        px = spx / hz
        move_x = nx * px
        move_y = -ny * px  # up is negative
        if st.tx_prev is None:
            st.tx_prev, st.ty_prev = tpad_w // 2, tpad_h // 2
        tx_raw = int(max(0, min(tpad_w-1, (st.tx_prev if st.tx_prev is not None else 0) + move_x)))
        ty_raw = int(max(0, min(tpad_h-1, (st.ty_prev if st.ty_prev is not None else 0) + move_y)))

    if st.tx_prev is None:
        tx, ty = tx_raw, ty_raw
    else:
        tx = int(st.tx_prev + smooth*(tx_raw - st.tx_prev))
        ty = int(st.ty_prev + smooth*(ty_raw - st.ty_prev))
    st.tx_prev, st.ty_prev = tx, ty

    # ----- Wiimote mapping -> DS4 bits -----
    face = 0
    ps = 0

    # A/B/1/2 -> Cross/Circle/Square/Triangle
    if is_binding_down(binds.get("wm_a"), xi): face |= BTN_CROSS
    if is_binding_down(binds.get("wm_b"), xi): face |= BTN_CIRCLE
    if is_binding_down(binds.get("wm_1"), xi): face |= BTN_SQUARE
    if is_binding_down(binds.get("wm_2"), xi): face |= BTN_TRIANGLE

    # + / − / Home -> Options / Share / PS
    if is_binding_down(binds.get("wm_plus"), xi):  ps |= OPTIONS_BTN
    if is_binding_down(binds.get("wm_minus"), xi): ps |= SHARE_BTN
    if is_binding_down(binds.get("wm_home"), xi):  ps |= PS_BTN

    # Toggle offscreen (debounce 150 ms)
    if is_binding_down(binds.get("toggle_off"), xi):
        now_us = time.perf_counter_ns() // 1000
        if now_us - st.last_toggle_us >= 150_000:
            st.offscreen = not st.offscreen
            st.last_toggle_us = now_us
    active = 0 if st.offscreen else 1

    # D-Pad via synthetic LS (easy to bind in Cemu)
    mag = int(max(0, min(255, vals["lstick_magnitude"])))
    lx = 128; ly = 128
    if is_binding_down(binds.get("wm_dpad_left"), xi):  lx = 128 - mag//2
    if is_binding_down(binds.get("wm_dpad_right"), xi): lx = 128 + mag//2
    if is_binding_down(binds.get("wm_dpad_up"), xi):    ly = 128 - mag//2
    if is_binding_down(binds.get("wm_dpad_down"), xi):  ly = 128 + mag//2

    # ----- Shake/spins (W/E) with adjustable speeds -----
    w_down = is_binding_down(binds.get("spin_w"), xi)
    e_down = is_binding_down(binds.get("spin_e"), xi)

    # pulse bookkeeping
    if not hasattr(st, "prev_w"): st.prev_w = False
    if not hasattr(st, "prev_e"): st.prev_e = False
    if not hasattr(st, "dir_w"):  st.dir_w = 1.0
    if not hasattr(st, "dir_e"):  st.dir_e = 1.0
    if not hasattr(st, "w_pulse_left"): st.w_pulse_left = 0
    if not hasattr(st, "e_pulse_left"): st.e_pulse_left = 0
    if not hasattr(st, "w_cooldown"):   st.w_cooldown = 0
    if not hasattr(st, "e_cooldown"):   st.e_cooldown = 0

    if w_down and not st.prev_w:
        st.dir_w *= -1.0
        st.w_pulse_left = frames_for_ms(vals["pulse_ms"], hz)
        st.w_cooldown = 0
    if e_down and not st.prev_e:
        st.dir_e *= -1.0
        st.e_pulse_left = frames_for_ms(vals["pulse_ms"], hz)
        st.e_cooldown = 0
    st.prev_w = w_down
    st.prev_e = e_down

    if w_down:
        if st.w_pulse_left == 0:
            if st.w_cooldown > 0:
                st.w_cooldown -= 1
            else:
                st.w_pulse_left = frames_for_ms(vals["pulse_ms"], hz)
                st.w_cooldown = frames_for_ms(vals["cooldown_ms"], hz)
    else:
        st.w_pulse_left = 0; st.w_cooldown = 0

    if e_down:
        if st.e_pulse_left == 0:
            if st.e_cooldown > 0:
                st.e_cooldown -= 1
            else:
                st.e_pulse_left = frames_for_ms(vals["pulse_ms"], hz)
                st.e_cooldown = frames_for_ms(vals["cooldown_ms"], hz)
    else:
        st.e_pulse_left = 0; st.e_cooldown = 0

    # base accel/gyro
    ax = 0.0; ay = 0.0; az = G
    if st.w_pulse_left > 0:
        ax += st.dir_w * float(vals["w_pulse_ax"])
        az += st.dir_w * float(vals["pulse_az"])
        st.w_pulse_left -= 1
    if st.e_pulse_left > 0:
        ay += st.dir_e * float(vals["e_pulse_ay"])
        az += st.dir_e * float(vals["pulse_az"])
        st.e_pulse_left -= 1

    gx = (st.dir_e * float(vals["spin_x_dps"])) if e_down else 0.0
    gy = 0.0
    gz = (st.dir_w * float(vals["twirl_z_dps"])) if w_down else 0.0

    # ----- NEW: Twist keys (gyro-only, no linear accel) -----
    twist = float(vals["twist_dps"])
    if is_binding_down(binds.get("mv_front"), xi):
        gx += twist      # pitch forward
    if is_binding_down(binds.get("mv_back"), xi):
        gx -= twist      # pitch backward
    if is_binding_down(binds.get("mv_left"), xi):
        gy -= twist      # roll left
    if is_binding_down(binds.get("mv_right"), xi):
        gy += twist      # roll right

    ts_us = time.perf_counter_ns() // 1000

    payload = bytearray()
    payload += common_begin()
    payload += b"\x01"                           # is_active
    payload += struct.pack("<I", st.idx)         # packet num
    payload += b"\x00"
    payload += struct.pack("<B", face)           # face buttons
    payload += struct.pack("<B", ps)             # PS/share/options
    payload += (b"\x01" if active else b"\x00")  # touch active
    payload += bytes([lx, ly, 0x80, 0x80])       # sticks (LX,LY,RX,RY)
    payload += b"\x00"*12
    payload += struct.pack("<BBHH", 1 if active else 0, 1, tx, ty)  # finger 1
    payload += struct.pack("<BBHH", 0, 0, 0, 0)                     # finger 2
    payload += struct.pack("<Q", ts_us)          # timestamp
    payload += struct.pack("<fff", ax, ay, az)   # accel
    payload += struct.pack("<fff", gx, gy, gz)   # gyro
    return pack_header(0x100002, bytes(payload))

def server_thread():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT))
    try:
        s.ioctl(socket.SIO_UDP_CONNRESET, b'\x00\x00\x00\x00')
    except (AttributeError, OSError):
        pass
    s.setblocking(False)

    log(f"Listening on udp://{HOST}:{PORT}")

    subs = set()
    st = State()

    with config.lock:
        hz = max(1, int(config.values["hz"]))
    period = 1.0 / hz
    next_tick = time.perf_counter() + period

    winmm.timeBeginPeriod(1)
    try:
        while not config.want_stop:
            # Rebind capture
            with config.lock:
                target = config.rebind_target
                deadline = config.rebind_deadline
            if target:
                xi = xinput_get_state(0)
                got = scan_next_pressed(xi)
                if got:
                    kind, code = got
                    with config.lock:
                        config.bindings[target] = (kind, int(code))
                        config.rebind_target = None
                        config.rebind_deadline = 0.0
                    log(f"Rebind '{target}' -> {binding_name((kind,code))}")
                elif time.time() > deadline:
                    config.cancel_rebind()
                    log(f"Rebind '{target}' canceled (timeout).")

            # Live HZ update
            with config.lock:
                hz_now = max(1, int(config.values["hz"]))
            if hz_now != hz:
                hz = hz_now
                period = 1.0 / hz
                next_tick = time.perf_counter() + period
                log(f"HZ updated to {hz}")

            timeout = max(0.0, next_tick - time.perf_counter())
            try:
                r, _, _ = select.select([s], [], [], timeout)
            except OSError:
                r = []

            if r:
                try:
                    data, addr = s.recvfrom(2048)
                except (BlockingIOError, ConnectionResetError, OSError):
                    data = None
                if data and data[:4] == MAGIC_C:
                    msg_type = struct.unpack_from("<I", data, 16)[0]
                    if msg_type == 0x100000:
                        s.sendto(resp_version(), addr)
                    elif msg_type == 0x100001:
                        s.sendto(resp_list_ports(), addr)
                    elif msg_type == 0x100002:
                        if addr not in subs:
                            subs.add(addr)
                            log(f"Subscriber: {addr[0]}:{addr[1]}")
                        with config.lock:
                            config.subs_count = len(subs)

            now = time.perf_counter()
            if now >= next_tick:
                if subs:
                    pkt = resp_data(st)
                    for a in tuple(subs):
                        try:
                            s.sendto(pkt, a)
                        except OSError:
                            subs.discard(a)
                    with config.lock:
                        config.subs_count = len(subs)
                missed = int((now - next_tick) / period)
                next_tick += (missed + 1) * period
    finally:
        winmm.timeEndPeriod(1)
        s.close()
        log("Server stopped.")

# ------------------------------ GUI (DearPyGui) ------------------------------

IDS = {
    "log_child": "log_child",
    "subs_text": "subs_text",
    "host_text": "host_text",
    "port_text": "port_text",
    "ptr_combo": "ptr_combo",

    # controls we want to sync on reset
    "hz_slider": "hz_slider",
    "invert_y": "invert_y",
    "smooth_slider": "smooth_slider",
    "cursor_speed": "cursor_speed",
    "deadzone": "deadzone",
    "tpad_w": "tpad_w",
    "tpad_h": "tpad_h",
    "lstick_mag": "lstick_mag",
    "bindings_file": "bindings_file",

    # Motion/Shake/Twist tuning sliders (sync too)
    "twirl_z_dps": "twirl_z_dps",
    "spin_x_dps": "spin_x_dps",
    "w_pulse_ax": "w_pulse_ax",
    "e_pulse_ay": "e_pulse_ay",
    "pulse_az": "pulse_az",
    "pulse_ms": "pulse_ms",
    "cooldown_ms": "cooldown_ms",
    "twist_dps": "twist_dps",
}

BIND_LABEL_TAG = {}
REBIND_BTN_TAG  = {}
for key,_ in ACTIONS_WIIMOTE + ACTIONS_EXTRA + ACTIONS_TWIST:
    BIND_LABEL_TAG[key] = f"bind_label_{key}"
    REBIND_BTN_TAG[key] = f"rebind_btn_{key}"

def on_slider_change(sender, app_data, user_data):
    key = user_data
    with config.lock:
        config.values[key] = app_data

def on_checkbox(sender, app_data, user_data):
    key = user_data
    with config.lock:
        config.values[key] = bool(app_data)

def on_combo(sender, app_data, user_data):
    key = user_data
    with config.lock:
        config.values[key] = str(app_data)

def on_input_text(sender, app_data, user_data):
    key = user_data
    with config.lock:
        config.values[key] = str(app_data)

def on_click_rebind(sender, app_data, user_data):
    action = user_data
    config.begin_rebind(action)
    log(f"Rebind '{action}' started: press any key or XInput button...")

def on_save_config(sender, app_data, user_data):
    config.save()

def on_save_bindings(sender, app_data, user_data):
    with config.lock:
        fn = config.values.get("bindings_filename", "bindings_user.json")
    if not fn.lower().endswith(".json"):
        fn += ".json"
    config.save_bindings_only(fn)

def on_load_bindings(sender, app_data, user_data):
    with config.lock:
        fn = config.values.get("bindings_filename", "bindings_user.json")
    if not fn.lower().endswith(".json"):
        fn += ".json"
    config.load_bindings_only(fn)

def sync_controls_from_config():
    with config.lock:
        dpg.set_value(IDS["hz_slider"],           config.values["hz"])
        dpg.set_value(IDS["invert_y"],            config.values["invert_y"])
        dpg.set_value(IDS["smooth_slider"],       config.values["smooth"])
        dpg.set_value(IDS["ptr_combo"],           config.values["pointer_source"])
        dpg.set_value(IDS["cursor_speed"],        config.values["cursor_speed_px_s"])
        dpg.set_value(IDS["deadzone"],            config.values["stick_deadzone"])
        dpg.set_value(IDS["tpad_w"],              config.values["tpad_w"])
        dpg.set_value(IDS["tpad_h"],              config.values["tpad_h"])
        dpg.set_value(IDS["lstick_mag"],          config.values["lstick_magnitude"])
        dpg.set_value(IDS["bindings_file"],       config.values["bindings_filename"])

        dpg.set_value(IDS["twirl_z_dps"],         config.values["twirl_z_dps"])
        dpg.set_value(IDS["spin_x_dps"],          config.values["spin_x_dps"])
        dpg.set_value(IDS["w_pulse_ax"],          config.values["w_pulse_ax"])
        dpg.set_value(IDS["e_pulse_ay"],          config.values["e_pulse_ay"])
        dpg.set_value(IDS["pulse_az"],            config.values["pulse_az"])
        dpg.set_value(IDS["pulse_ms"],            config.values["pulse_ms"])
        dpg.set_value(IDS["cooldown_ms"],         config.values["cooldown_ms"])
        dpg.set_value(IDS["twist_dps"],           config.values["twist_dps"])

def on_reset_defaults(sender, app_data, user_data):
    config.reset_to_defaults(delete_config_file=True)
    sync_controls_from_config()
    log("All values and bindings reset to defaults.")

def build_bind_table(title, actions):
    dpg.add_text(title)
    with dpg.table(header_row=True, resizable=True, borders_innerH=True, borders_innerV=True, borders_outerH=True, borders_outerV=True):
        dpg.add_table_column(label="Action")
        dpg.add_table_column(label="Current")
        dpg.add_table_column(label="Rebind")
        for key, label in actions:
            with dpg.table_row():
                dpg.add_text(label)
                with config.lock:
                    b = config.bindings.get(key)
                dpg.add_text(binding_name(b), tag=BIND_LABEL_TAG[key])
                dpg.add_button(label="Rebind", tag=REBIND_BTN_TAG[key], user_data=key, callback=on_click_rebind)

def build_gui():
    dpg.create_context()
    dpg.create_viewport(title=APP_TITLE, width=1100, height=930)
    dpg.setup_dearpygui()

    with dpg.window(label=APP_TITLE, tag="main", width=1080, height=900, no_collapse=True):
        dpg.add_text("Server status")
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_text("Host:"); dpg.add_text(HOST, tag=IDS["host_text"])
            dpg.add_spacer(width=20)
            dpg.add_text("Port:"); dpg.add_text(str(PORT), tag=IDS["port_text"])
            dpg.add_spacer(width=20)
            dpg.add_text("Subs: "); dpg.add_text("0", tag=IDS["subs_text"])

        dpg.add_separator()
        dpg.add_text("Live parameters")
        with dpg.group(horizontal=True):
            dpg.add_slider_int(label="HZ", default_value=config.values["hz"], min_value=60, max_value=250, width=220, callback=on_slider_change, user_data="hz", tag=IDS["hz_slider"])
            dpg.add_checkbox(label="Invert Y", default_value=config.values["invert_y"], callback=on_checkbox, user_data="invert_y", tag=IDS["invert_y"])
            dpg.add_slider_float(label="Smoothing", default_value=config.values["smooth"], min_value=0.0, max_value=1.0, width=220, callback=on_slider_change, user_data="smooth", tag=IDS["smooth_slider"])
        dpg.add_separator()

        dpg.add_text("Pointer (IR) — Source & dynamics")
        with dpg.group(horizontal=True):
            dpg.add_combo(POINTER_SOURCES, default_value=config.values["pointer_source"], width=160, callback=on_combo, user_data="pointer_source", tag=IDS["ptr_combo"])
            dpg.add_slider_float(label="Cursor speed (px/s)", default_value=config.values["cursor_speed_px_s"], min_value=100.0, max_value=4000.0, width=300, callback=on_slider_change, user_data="cursor_speed_px_s", tag=IDS["cursor_speed"])
            dpg.add_slider_int(label="Stick deadzone", default_value=config.values["stick_deadzone"], min_value=0, max_value=20000, width=240, callback=on_slider_change, user_data="stick_deadzone", tag=IDS["deadzone"])
        with dpg.group(horizontal=True):
            dpg.add_slider_int(label="Touchpad W", default_value=config.values["tpad_w"], min_value=320, max_value=4096, width=240, callback=on_slider_change, user_data="tpad_w", tag=IDS["tpad_w"])
            dpg.add_slider_int(label="Touchpad H", default_value=config.values["tpad_h"], min_value=240, max_value=2048, width=240, callback=on_slider_change, user_data="tpad_h", tag=IDS["tpad_h"])

        dpg.add_separator()
        build_bind_table("Bindings — Wiimote", ACTIONS_WIIMOTE)

        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_slider_int(label="D-Pad (LS) Magnitude", default_value=config.values["lstick_magnitude"], min_value=0, max_value=255, width=300, callback=on_slider_change, user_data="lstick_magnitude", tag=IDS["lstick_mag"])

        dpg.add_separator()
        build_bind_table("Bindings — Extra (Shake/Toggle)", ACTIONS_EXTRA)

        dpg.add_separator()
        # NEW: Twist bindings section (independent of D-Pad; gyro-only)
        build_bind_table("Bindings — Twist (hold to twist controller)", ACTIONS_TWIST)

        dpg.add_separator()
        dpg.add_text("Motion / Shake / Twist Tuning")
        with dpg.group(horizontal=True):
            dpg.add_slider_float(label="Twirl Z speed (deg/s)", default_value=config.values["twirl_z_dps"], min_value=0.0, max_value=2000.0, width=280, callback=on_slider_change, user_data="twirl_z_dps", tag=IDS["twirl_z_dps"])
            dpg.add_slider_float(label="Spin X speed (deg/s)",  default_value=config.values["spin_x_dps"],  min_value=0.0, max_value=2000.0, width=280, callback=on_slider_change, user_data="spin_x_dps",  tag=IDS["spin_x_dps"])
        with dpg.group(horizontal=True):
            dpg.add_slider_float(label="Pulse AX (m/s²)", default_value=config.values["w_pulse_ax"], min_value=0.0, max_value=100.0, width=220, callback=on_slider_change, user_data="w_pulse_ax", tag=IDS["w_pulse_ax"])
            dpg.add_slider_float(label="Pulse AY (m/s²)", default_value=config.values["e_pulse_ay"], min_value=0.0, max_value=100.0, width=220, callback=on_slider_change, user_data="e_pulse_ay", tag=IDS["e_pulse_ay"])
            dpg.add_slider_float(label="Pulse AZ (m/s²)", default_value=config.values["pulse_az"],  min_value=0.0, max_value=100.0, width=220, callback=on_slider_change, user_data="pulse_az",  tag=IDS["pulse_az"])
        with dpg.group(horizontal=True):
            dpg.add_slider_int(label="Pulse ms", default_value=config.values["pulse_ms"], min_value=4, max_value=200, width=200, callback=on_slider_change, user_data="pulse_ms", tag=IDS["pulse_ms"])
            dpg.add_slider_int(label="Cooldown ms", default_value=config.values["cooldown_ms"], min_value=0, max_value=200, width=220, callback=on_slider_change, user_data="cooldown_ms", tag=IDS["cooldown_ms"])
        with dpg.group(horizontal=True):
            dpg.add_slider_float(label="Twist rate (deg/s)",  default_value=config.values["twist_dps"],   min_value=0.0, max_value=720.0, width=260, callback=on_slider_change, user_data="twist_dps",  tag=IDS["twist_dps"])

        dpg.add_separator()
        dpg.add_text("Config & Bindings")
        with dpg.group(horizontal=True):
            dpg.add_button(label="Save Config", callback=on_save_config)
            dpg.add_button(label="Reset to Defaults", callback=on_reset_defaults)
        with dpg.group(horizontal=True):
            dpg.add_input_text(label="Bindings file (.json)", default_value=config.values["bindings_filename"], width=260, callback=on_input_text, user_data="bindings_filename", tag=IDS["bindings_file"])
            dpg.add_button(label="Save Bindings (.json)", callback=on_save_bindings)
            dpg.add_button(label="Load Bindings (.json)", callback=on_load_bindings)

        dpg.add_separator()
        dpg.add_text("Log:")
        dpg.add_child_window(tag=IDS["log_child"], height=240, autosize_x=True, horizontal_scrollbar=True)

    dpg.set_primary_window("main", True)
    dpg.show_viewport()

def gui_mainloop():
    th = threading.Thread(target=server_thread, daemon=True)
    th.start()
    while dpg.is_dearpygui_running():
        # flush logs
        while log_queue:
            line = log_queue.popleft()
            dpg.add_text(line, parent=IDS["log_child"])
            dpg.set_y_scroll(IDS["log_child"], 1e9)

        # update binding labels & subs count
        with config.lock:
            for k,_ in ACTIONS_WIIMOTE + ACTIONS_EXTRA + ACTIONS_TWIST:
                name = binding_name(config.bindings.get(k))
                if config.rebind_target == k:
                    name = f"{name}  (waiting...)"
                dpg.set_value(BIND_LABEL_TAG[k], name)
            dpg.set_value(IDS["subs_text"], str(config.subs_count))

        dpg.render_dearpygui_frame()
        time.sleep(0.01)

    config.want_stop = True
    dpg.destroy_context()

# ------------------------------ MAIN ------------------------------

if __name__ == "__main__":
    build_gui()
    gui_mainloop()
