# virtualwiimote

![VWiimote Logo](https://i.ibb.co/vxhkNqqm/Add-a-heading.png)  

▶️ [Watch the tutorial](https://youtu.be/2EJzKAlKOfM?t=16s)

[<img src="https://i.imgur.com/8dQpVxG.png" width="560" alt="Watch the video">](https://youtu.be/2EJzKAlKOfM?t=16s)



Turn **anything**—mouse, keyboard, or Xbox/DirectInput pad—into a **virtual Wiimote** for **Cemu**, complete with a **software IR (infrared) pointer**.  
No phone, no Bluetooth, no real Wiimote required.

- ✅ Tested on **Cemu 2.0.74** with **Wii Party U**
- 🪟 **Windows** only (uses Win32 / WinMM / XInput)
- 🌐 DSU (Cemuhook) server: **127.0.0.1:26761** *(non-default on purpose)*

---

## Why this exists

I couldn’t get a physical Wiimote, and phone/DSU solutions kept breaking across Cemu versions. I dug into how **Cemu’s DSU API** handles inputs; despite claims that *“IR over DSU is impossible (only motion)”*, **IR does work**—and motion too—when you feed the right data. 🎯

Right now you get a **software IR pointer** plus **twirl/spin** “shake” motions. More motion profiles are planned.

---

## Features

- **Software IR pointer**
  - Use your **mouse** or an **XInput stick** (LS/RS) to aim in IR-required games.
  - Live tuning: cursor speed (px/s), deadzone, smoothing, invert Y, virtual touchpad size.

- **Full Wiimote layout (remappable)**
  - **A**, **B (Trigger)**, **1**, **2**, **Plus (+)**, **Minus (−)**, **Home**, **D-Pad (↑↓←→)**.
  - Bind to any **keyboard key** or **XInput button** — bindings are **server-side**.

- **Motion “shake” pulses**
  - Twirl/Spin channels for games that react to jolts (more nuanced motion coming).

- **DearPyGui UI**
  - Clean interface to switch pointer source, tweak feel, and **click-to-rebind** everything.

- **Low CPU**
  - Cooperative scheduler (no busy-wait), precise tick timing.

---

## Requirements

- Windows 10/11
- Python 3.8+ (available as `py` / `python` in PATH)
- Cemu with DSU/Cemuhook input enabled

---

## Installation

1) Install Python 3  
   Grab it from https://www.python.org/downloads/ and check **“Add Python to PATH.”**

2) Install the GUI dependency (DearPyGui)

    py -m pip install -U dearpygui

3) Run the app (replace the filename if yours differs)

    py vwiimote.py

---

## Configure in Cemu

1. With the app running, open **Cemu → Options → Input Settings**.  
2. Pick the **controller slot** you want to configure.  
3. Set **Emulated Controller** to **Wiimote**.  
   - For games that also need the GamePad (e.g., **Wii Party U**), put **Wiimote** on controller **#2**.  
4. Click the **➕** and choose **DSUController** as the API.  
5. Set **IP = 127.0.0.1** and **Port = 26761**.  
   - This app intentionally uses **26761** (not the common 26760) to avoid conflicts.  
6. In the dropdown, select **Controller #1**.  
7. Enable **MotionPlus** and **Motion** (one checkbox in the DSU panel, the other in DSU **Settings**).
8. IMPORTANT: **BIND AGAIN ALL BUTTONS IN CEMU, literally just copy the bindings of the WiiMote default buttons that you have in the app to CEMU (except motion buttons, only WiiMote default buttons like A, B, + -, 1 & 2)**
   
When you configure your buttons inside Virtual WiiMote, those mappings exist only inside the DSU server (the app) — Cemu doesn’t automatically “see” what keys or buttons you assigned there.
The DSU protocol just tells Cemu “a Wiimote button was pressed”, but not which physical key or controller button triggered it.

That’s why after you finish setting up the Virtual WiiMote app, you still have to open Cemu’s Input Settings and bind those same WiiMote buttons again, so that Cemu knows what to expect.
   
**Screenshots**

![Cemu DSU Setup](https://i.ibb.co/tTGK13JN/Screenshot-2025-10-22-005409.png)  
![Bindings in Cemu](https://i.ibb.co/HfxdBc62/Screenshot-2025-10-22-005430.png)

---

## Using the app

- **Pointer source**: choose `mouse`, `xinput_rs` (right stick), or `xinput_ls` (left stick).  
- **Tune IR feel**: adjust cursor speed, deadzone, smoothing, invert Y, and touchpad size.  
- **Rebind everything**: click **Rebind**, then press the keyboard key or XInput button.  
- **Server-side bindings**: Cemu doesn’t care what you mapped internally — it only sees DSU output.  
  - After changing bindings in the app, (re)bind inside **Cemu** so it recognizes inputs cleanly.

---

## Defaults (fully editable in the UI)

| Wiimote Action | Default |
|---|---|
| A | `A` |
| B (Trigger) | `S` |
| 1 / 2 | `1` / `2` |
| Plus / Minus | `+` / `-` |
| Home | `Home` |
| D-Pad | Arrow keys (← → ↑ ↓) |
| Off-screen toggle | `F8` |
| Shake/Twirl (Z) | `W` |
| Shake/Spin  (X) | `E` |

**IR driver:** `mouse` by default (switch to **RS**/**LS** and tweak speed/deadzone as needed).

---

## Tips & Troubleshooting

- **Cemu doesn’t detect DSU**
  - Ensure the app is running.
  - Verify **IP = 127.0.0.1**, **Port = 26761**.
  - Allow Python through **Windows Firewall**.

- **Pointer too slow/fast**
  - Change cursor speed (px/s), deadzone, smoothing.

- **CPU usage**
  - Should be very low. If not, lower **HZ** in the UI or close overlays.

---

## Status

Early but working. Expect the odd bug. I’m releasing this because I’m **finally** playing the IR-required stuff I’ve wanted for years. More motion profiles and mapping options are on the way.

---

## Credits

- UI: **DearPyGui**  
- Protocol groundwork: **Cemuhook / DSU** ecosystem

---

## License

MIT
