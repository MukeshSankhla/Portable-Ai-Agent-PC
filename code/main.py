"""
main.py  –  OpenClaw Agent Status Display
══════════════════════════════════════════
Hardware : Raspberry Pi Pico (RP2040)
Display  : SSD1306 128×64  –  SDA→GP4  SCL→GP5
Serial   : USB cable → /dev/ttyACM0  (no extra wiring)

On Ubuntu:
  screen /dev/ttyACM0 115200
  picocom -b 115200 /dev/ttyACM0
  echo "t" > /dev/ttyACM0

━━━  SERIAL COMMANDS  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  i                 →  IDLE
  t                 →  THINKING
  l                 →  LOADING  (indeterminate)
  l:<0-100>         →  LOADING  fixed %       l:75
  l:<0-100>:<msg>   →  LOADING  % + label     l:60:SENDING EMAIL
  s                 →  SUCCESS
  s:<msg>           →  SUCCESS  custom label  s:EMAIL SENT
  e                 →  ERROR
  e:<msg>           →  ERROR    custom label  e:AUTH FAILED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import time
import select
from machine import Pin, I2C
import ssd1306
from openclaw_ui import OpenClawUI


# ─────────────────────────────────────────────────────────────────────
#  HARDWARE
# ─────────────────────────────────────────────────────────────────────

i2c  = I2C(0, sda=Pin(4), scl=Pin(5), freq=400_000)
oled = ssd1306.SSD1306_I2C(128, 64, i2c)
ui   = OpenClawUI(oled)

print("OpenClaw Display")
print("OLED:", [hex(a) for a in i2c.scan()])
print("Commands: i  t  l  l:<pct>  l:<pct>:<msg>  s  s:<msg>  e  e:<msg>")
print("-" * 48)


# ─────────────────────────────────────────────────────────────────────
#  APP STATE
# ─────────────────────────────────────────────────────────────────────

class AppState:
    IDLE     = "idle"
    THINKING = "thinking"
    LOADING  = "loading"
    SUCCESS  = "success"
    ERROR    = "error"

    def __init__(self):
        self.state    = self.IDLE
        self.progress = None
        self.msg      = ""
        self.changed  = False

    def _set(self, state, progress=None, msg=""):
        self.state    = state
        self.progress = progress
        self.msg      = msg
        self.changed  = True

    def set_idle(self):
        self._set(self.IDLE)

    def set_thinking(self):
        self._set(self.THINKING)

    def set_loading(self, progress=None, msg="WORKING"):
        self._set(self.LOADING, progress=progress, msg=msg)

    def set_success(self, msg="DONE"):
        self._set(self.SUCCESS, msg=msg or "DONE")

    def set_error(self, msg="ERROR"):
        self._set(self.ERROR, msg=msg or "ERROR")

    def render(self, display, t):
        if   self.state == self.IDLE:
            display.draw_idle(t)
        elif self.state == self.THINKING:
            display.draw_thinking(t)
        elif self.state == self.LOADING:
            display.draw_loading(t, progress=self.progress, msg=self.msg or "WORKING")
        elif self.state == self.SUCCESS:
            display.draw_success(t, msg=self.msg)
        elif self.state == self.ERROR:
            display.draw_error(t, msg=self.msg)


app = AppState()


# ─────────────────────────────────────────────────────────────────────
#  COMMAND PARSER
# ─────────────────────────────────────────────────────────────────────

def apply_cmd(raw):
    cmd = raw.strip()
    if not cmd:
        return None

    lo = cmd.lower()

    # ── bare single-letter commands ───────────────────────────────────
    if lo == "i":
        app.set_idle()
        return "OK: IDLE"

    if lo == "t":
        app.set_thinking()
        return "OK: THINKING"

    if lo == "l":
        app.set_loading()
        return "OK: LOADING (indeterminate)"

    if lo == "s":
        app.set_success()
        return "OK: SUCCESS"

    if lo == "e":
        app.set_error()
        return "OK: ERROR"

    # ── commands with payload ─────────────────────────────────────────
    if ":" in cmd:
        parts = cmd.split(":", 2)   # max 3 parts: cmd, arg1, arg2
        head  = parts[0].lower()

        if head == "l":
            try:
                pct = int(parts[1])
                if not 0 <= pct <= 100:
                    raise ValueError
                label = parts[2].strip() if len(parts) > 2 else "WORKING"
                app.set_loading(progress=pct / 100.0, msg=label)
                return "OK: LOADING {}% '{}'".format(pct, app.msg)
            except (ValueError, IndexError):
                return "ERR: l:<0-100> or l:<0-100>:<msg>"

        if head == "s":
            # preserve original case for message
            msg = parts[1].strip() if len(parts) > 1 else "DONE"
            app.set_success(msg=msg)
            return "OK: SUCCESS '{}'".format(app.msg)

        if head == "e":
            msg = parts[1].strip() if len(parts) > 1 else "ERROR"
            app.set_error(msg=msg)
            return "OK: ERROR '{}'".format(app.msg)

    return "ERR: unknown '{}' – use i t l l:<pct> l:<pct>:<msg> s s:<msg> e e:<msg>".format(cmd)


# ─────────────────────────────────────────────────────────────────────
#  NON-BLOCKING USB STDIN READER
# ─────────────────────────────────────────────────────────────────────

_buf = []

def poll_stdin():
    """
    Called once per frame.  Reads all pending stdin bytes without
    blocking (select timeout=0).  Accumulates into _buf, executes
    on newline.  Latency ≤ 1 frame (~55 ms).
    """
    while True:
        r, _, _ = select.select([sys.stdin], [], [], 0)
        if not r:
            break
        ch = sys.stdin.read(1)
        if not ch:
            break
        b = ord(ch)

        if b in (0x0D, 0x0A):       # Enter
            if _buf:
                line = "".join(_buf)
                _buf.clear()
                reply = apply_cmd(line)
                if reply:
                    print(reply)

        elif b in (0x08, 0x7F):     # Backspace
            if _buf:
                _buf.pop()

        elif 0x20 <= b <= 0x7E:     # Printable ASCII
            if len(_buf) < 64:
                _buf.append(ch)


# ─────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────

FRAME_MS = 55    # ~18 fps

def main():
    t = 0
    while True:
        t0 = time.ticks_ms()

        # 1. check serial (non-blocking)
        poll_stdin()

        # 2. reset frame counter on state change → clean animation start
        if app.changed:
            app.changed = False
            t = 0
            print("[->] {}{}".format(
                app.state.upper(),
                " | " + app.msg if app.msg else ""
            ))

        # 3. render frame
        app.render(ui, t)
        t += 1

        # 4. pace to target fps
        elapsed = time.ticks_diff(time.ticks_ms(), t0)
        wait    = FRAME_MS - elapsed
        if wait > 0:
            time.sleep_ms(wait)


main()
