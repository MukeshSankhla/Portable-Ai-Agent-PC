"""
openclaw_ui.py  –  OpenClaw Agent Status Display
SSD1306 128×64 OLED  |  RPi Pico 2040  |  I2C SDA=GP4 SCL=GP5

OpenClaw is an AI agent that clears inboxes, sends emails,
manages calendars and checks in for flights via WhatsApp/Telegram.

This display shows the agent's current operational state with
purposeful, information-dense animations — not generic sci-fi.

LAYOUT (fixed, all states)
──────────────────────────────────────────────
  Y  0–10  │ TOPBAR  │ "OPENCLAW" brand + uptime clock   (11px)
  Y 11     │ divider line
  Y 12–50  │ CANVAS  │ state-specific animation          (39px)
  Y 51     │ divider line
  Y 52–63  │ STATUSBAR│ context message / sub-label      (12px)
──────────────────────────────────────────────

States & their visual language
  IDLE     – calm heartbeat pulse + connection dots
  THINKING – left: neural wave  /  right: task context text
  LOADING  – horizontal sweep bar + spinner glyph + pct
  SUCCESS  – checkmark build-up + radiating confirmation rings
  ERROR    – exclamation with inverted blink + error code
"""

import math

_PI2 = math.pi * 2

def _s(deg): return math.sin(math.radians(deg))
def _c(deg): return math.cos(math.radians(deg))
def _cl(v, lo, hi): return max(lo, min(hi, v))


# ──────────────────── tiny text helpers ──────────────────────────────
# SSD1306 .text() uses 8×8 font.  One char = 8px wide, 8px tall.
# Max chars in 128px = 16.  We budget 15 to keep a 1px margin.

def _centre_x(text, width=128):
    """Left x to centre `text` in `width` pixels (8px font)."""
    return max(0, (width - len(text) * 8) // 2)

def _right_x(text, width=128, margin=1):
    """Left x so `text` is right-aligned with `margin` px to spare."""
    return max(0, width - len(text) * 8 - margin)

def _truncate(text, max_chars):
    if len(text) <= max_chars:
        return text
    return text[:max_chars - 1] + "~"


# ─────────────────────── OpenClawUI ──────────────────────────────────

class OpenClawUI:

    W  = 128
    H  = 64

    # zone coords
    TB_Y  = 0;   TB_H  = 11   # topbar     rows 0–10
    DIV1  = 11                 # divider
    CV_Y  = 12;  CV_H  = 39   # canvas     rows 12–50
    DIV2  = 51                 # divider
    SB_Y  = 52;  SB_H  = 12   # statusbar  rows 52–63

    CV_CX = 64                 # canvas centre x
    CV_CY = 12 + 39 // 2      # canvas centre y  = 31

    def __init__(self, oled):
        self.o = oled

    # ─────────────────────────────────────────────────────────────────
    #  PIXEL-SAFE PRIMITIVES  (clip to canvas zone)
    # ─────────────────────────────────────────────────────────────────

    def _px(self, x, y, c=1):
        if 0 <= x < self.W and self.CV_Y <= y <= self.DIV2 - 1:
            self.o.pixel(x, y, c)

    def _circle(self, cx, cy, r, c=1):
        if r <= 0: return
        x, y, d = r, 0, 1 - r
        while x >= y:
            for dx, dy in [(x,y),(-x,y),(x,-y),(-x,-y),
                           (y,x),(-y,x),(y,-x),(-y,-x)]:
                self._px(cx+dx, cy+dy, c)
            y += 1
            d += (2*y+1) if d < 0 else (2*(y - (x:=x-1))+1)

    def _arc(self, cx, cy, r, a0, a1, c=1):
        """Draw arc from a0 to a1 degrees."""
        a = a0
        while a <= a1:
            self._px(int(cx + r*_c(a)), int(cy + r*_s(a)), c)
            a += 1

    def _spin_arc(self, cx, cy, r, off, length=120, c=1):
        s = int(off) % 360
        e = s + length
        if e <= 360:
            self._arc(cx, cy, r, s, min(e, 359), c)
        else:
            self._arc(cx, cy, r, s, 359, c)
            self._arc(cx, cy, r, 0, e % 360, c)

    def _line(self, x0, y0, x1, y1, c=1):
        """Bresenham line, clipped to canvas."""
        x0 = _cl(x0, 0, self.W-1);  x1 = _cl(x1, 0, self.W-1)
        y0 = _cl(y0, self.CV_Y, self.DIV2-1)
        y1 = _cl(y1, self.CV_Y, self.DIV2-1)
        self.o.line(x0, y0, x1, y1, c)

    def _hline_cv(self, y, x0=0, x1=None, c=1):
        if x1 is None: x1 = self.W
        if self.CV_Y <= y < self.DIV2:
            self.o.hline(x0, y, x1 - x0, c)

    def _fill_rect_cv(self, x, y, w, h, c=1):
        """fill_rect clipped to canvas zone."""
        y0 = _cl(y, self.CV_Y, self.DIV2)
        y1 = _cl(y + h, self.CV_Y, self.DIV2)
        if y1 > y0 and w > 0:
            self.o.fill_rect(x, y0, w, y1 - y0, c)

    # ─────────────────────────────────────────────────────────────────
    #  SHARED CHROME ELEMENTS
    # ─────────────────────────────────────────────────────────────────

    def _draw_topbar(self, t, right_label=""):
        """
        Fixed topbar: "OPENCLAW" left  |  right_label right
        Uptime ticks as a tiny dot-counter bottom-right of topbar.
        """
        o = self.o
        o.fill_rect(0, self.TB_Y, self.W, self.TB_H, 0)
        o.text("OPENCLAW", 1, 1, 1)
        if right_label:
            rx = _right_x(right_label, margin=1)
            o.text(right_label, rx, 1, 1)
        o.hline(0, self.DIV1, self.W, 1)

    def _draw_statusbar(self, text, invert=False):
        """Footer statusbar – centred text, optional invert."""
        o = self.o
        o.hline(0, self.DIV2, self.W, 1)
        o.fill_rect(0, self.SB_Y, self.W, self.SB_H, 1 if invert else 0)
        msg = _truncate(text.upper(), 15)
        x = _centre_x(msg)
        o.text(msg, x, self.SB_Y + 2, 0 if invert else 1)

    def _activity_dots(self, t, n=4, cx=None):
        """
        Travelling dot: one bright dot sweeps through n positions.
        Used as a subtle 'live' indicator in topbar.
        """
        if cx is None: cx = self.W - 2 - (n - 1) * 3
        pos = (t // 4) % n
        for i in range(n):
            x = cx + i * 3
            self.o.pixel(x, self.TB_H - 3, 1 if i == pos else 0)
            self.o.pixel(x, self.TB_H - 3, 1)  # always draw dot base
        # bright dot
        self.o.pixel(cx + pos * 3, self.TB_H - 3, 1)

    # ─────────────────────────────────────────────────────────────────
    #  STATE: IDLE
    # ─────────────────────────────────────────────────────────────────
    #
    #  Concept: "Connected and waiting."
    #  Centre: slow heartbeat pulse ring (breathes in/out)
    #  Left of centre: small WiFi-style arc stack = connectivity
    #  Right of centre: three channel dots (WhatsApp/Telegram/chat)
    #    blinking in staggered rhythm = "channels alive"
    #  Status: "READY"
    #
    def draw_idle(self, t):
        o = self.o
        o.fill(0)

        cx, cy = self.CV_CX, self.CV_CY   # 64, 31

        # ── heartbeat pulse (centre) ──────────────────────────────────
        # r breathes: 6→14→6 over 60 frames
        phase = (t % 60) / 60.0
        if phase < 0.3:
            r = 6 + int(phase / 0.3 * 8)     # expand  6→14
        elif phase < 0.5:
            r = 14 - int((phase-0.3)/0.2 * 8) # contract 14→6
        else:
            r = 6                              # rest

        self._circle(cx, cy, r)
        # solid centre dot
        o.fill_rect(cx-1, _cl(cy-1, self.CV_Y, self.DIV2-1), 3, 3, 1)

        # faint outer ring – always at r+5, shows the "max" boundary
        self._circle(cx, cy, 19)

        # ── connectivity arcs (left panel, x 5-30) ───────────────────
        # Three arcs like a WiFi symbol — each one blinks in sequence
        arc_cx, arc_cy = 22, cy + 6
        for i, (ar, blink_offset) in enumerate([(4, 0), (8, 8), (13, 16)]):
            # arc is lit if uptime mod period is past its blink_offset
            lit = ((t + blink_offset) // 12) % 3 >= i
            if lit:
                self._arc(arc_cx, arc_cy, ar, 210, 330, 1)
        # centre dot of WiFi
        self._px(arc_cx, arc_cy, 1)
        self._px(arc_cx+1, arc_cy, 1)

        # ── channel alive dots (right panel, x 96-122) ───────────────
        # Three dots for WA / TG / Chat, staggered blink
        labels = ["WA", "TG", "CH"]
        for i, lbl in enumerate(labels):
            dy = cy - 8 + i * 8
            dy = _cl(dy, self.CV_Y + 1, self.DIV2 - 9)
            blink_on = ((t + i * 7) // 10) % 3 != 0
            # dot
            self._px(98, dy + 3, 1)
            # label
            if 0 <= dy and dy + 8 < self.DIV2:
                o.text(lbl, 102, dy, 1 if blink_on else 0)

        # ── chrome ────────────────────────────────────────────────────
        self._draw_topbar(t, right_label="IDLE")
        self._draw_statusbar("READY")
        o.show()

    # ─────────────────────────────────────────────────────────────────
    #  STATE: THINKING
    # ─────────────────────────────────────────────────────────────────
    #
    #  Concept: "Processing a task."
    #  Left 58px : neural activity — scrolling sine wave with
    #              intensity that rises/falls to show "computation"
    #  Right 66px: task context — two lines of small scrolling text
    #              cycling through agent actions
    #  Divider vline at x=62
    #  Status: "PROCESSING"
    #
    _TASKS = [
        "READING MAIL",
        "CALENDAR CHK",
        "DRAFTING MSG",
        "FLIGHT CHK-IN",
        "INBOX TRIAGE",
        "REPLY QUEUE",
    ]

    def draw_thinking(self, t):
        o = self.o
        o.fill(0)

        # ── neural wave (left 0–61) ───────────────────────────────────
        # Scrolling sine wave; amplitude modulated by a slow envelope
        env = 0.5 + 0.5 * _s(t * 2)          # 0.0 → 1.0 breathing
        for x in range(0, 61, 1):
            # two harmonics for an "alive" waveform
            y_off = (int(8 * env * _s(x * 8 + t * 12)) +
                     int(3 * _s(x * 20 + t * 18)))
            y = _cl(self.CV_CY + y_off, self.CV_Y + 1, self.DIV2 - 2)
            self._px(x, y, 1)
            # thicken when amplitude is high
            if env > 0.7:
                self._px(x, _cl(y-1, self.CV_Y+1, self.DIV2-2), 1)

        # small label under wave
        o.text("NEURAL", 2, self.DIV2 - 9, 1)

        # ── vertical divider ──────────────────────────────────────────
        o.vline(62, self.CV_Y, self.CV_H, 1)

        # ── task context (right 64–127) ───────────────────────────────
        # Two task lines cycle through _TASKS with a 40-frame period
        period = 40
        slot = (t // period) % len(self._TASKS)
        next_slot = (slot + 1) % len(self._TASKS)
        # scroll-in offset: last 8 frames of period do a 1-line scroll up
        scroll_phase = t % period
        scroll_y_off = 0
        if scroll_phase >= period - 8:
            scroll_y_off = -(scroll_phase - (period - 8))   # 0 → -8

        # Line 1: current task
        task1 = self._TASKS[slot]
        task2 = self._TASKS[next_slot]
        ty1 = self.CV_Y + 4 + scroll_y_off
        ty2 = ty1 + 12

        if self.CV_Y <= ty1 < self.DIV2 - 7:
            o.text(_truncate(task1, 8), 65, ty1, 1)
        if self.CV_Y <= ty2 < self.DIV2 - 7:
            o.text(_truncate(task2, 8), 65, ty2, 1)

        # animated "..." below
        dots = "." * ((t // 5) % 4)
        dot_y = self.CV_Y + 28
        if dot_y + 8 < self.DIV2:
            o.text(dots + "   ", 65, dot_y, 1)

        # ── chrome ────────────────────────────────────────────────────
        self._draw_topbar(t, right_label="THINK")
        self._draw_statusbar("PROCESSING")
        o.show()

    # ─────────────────────────────────────────────────────────────────
    #  STATE: LOADING
    # ─────────────────────────────────────────────────────────────────
    #
    #  Concept: "Executing a task — progress trackable."
    #  Centre: big bold percentage number
    #  Below %: segmented progress bar (full width)
    #  Top-left corner: animated spinner glyph (/ - \ |)
    #  Top-right: elapsed frame ticker
    #  Status: shows the msg passed in (e.g. "SENDING EMAIL")
    #
    _SPINNER = r"/-\|"

    def draw_loading(self, t, progress=None, msg="WORKING"):
        o = self.o
        o.fill(0)

        # ── spinner glyph (top-left of canvas) ───────────────────────
        spin_ch = self._SPINNER[t % 4]
        o.text(spin_ch, 2, self.CV_Y + 2, 1)

        # ── frame ticker (top-right of canvas) ───────────────────────
        tick = "{:04d}".format(t % 9999)
        o.text(tick, _right_x(tick, margin=2), self.CV_Y + 2, 1)

        # ── big percentage (centre canvas) ───────────────────────────
        if progress is not None:
            pct = int(_cl(progress, 0.0, 1.0) * 100)
            pct_str = "{:3d}%".format(pct)
        else:
            # indeterminate: count up and loop
            pct_str = " {}% ".format((t * 2) % 101)
            pct = (t * 2) % 101

        # draw each digit large using 2×2 pixel blocks (DIY large font)
        # centre the pct_str in the canvas
        self._draw_big_number(pct_str.strip(), self.CV_CY - 2)

        # ── progress bar (bottom of canvas) ──────────────────────────
        bar_y  = self.DIV2 - 8
        bar_x  = 2
        bar_w  = self.W - 4
        bar_h  = 5
        o.rect(bar_x, bar_y, bar_w, bar_h, 1)

        if progress is not None:
            filled = int(_cl(progress, 0.0, 1.0) * (bar_w - 2))
        else:
            # bouncing fill for indeterminate
            sweep = (t % 50) / 50.0
            filled = int((sweep if sweep < 0.5 else 1.0 - sweep) * 2 * (bar_w - 2))

        if filled > 0:
            # segmented fill
            sx = bar_x + 1
            seg, gap = 5, 2
            while sx + seg <= bar_x + 1 + filled:
                o.fill_rect(sx, bar_y + 1, seg, bar_h - 2, 1)
                sx += seg + gap

        # ── chrome ────────────────────────────────────────────────────
        self._draw_topbar(t, right_label="LOAD")
        self._draw_statusbar(msg)
        o.show()

    def _draw_big_number(self, text, cy):
        """
        Draw text as 2×3 scaled characters (each pixel → 2×2 block).
        Each 8×8 char becomes 16×16.  Centres the string horizontally.
        """
        import framebuf
        # render to a tiny 1-bit buffer then scale-blit to OLED
        char_w, char_h = 8, 8
        scale = 2
        n = len(text)
        total_w = n * char_w * scale
        start_x = max(0, (self.W - total_w) // 2)
        start_y = _cl(cy - char_h * scale // 2, self.CV_Y, self.DIV2 - char_h * scale)

        # blit each character individually scaled
        for i, ch in enumerate(text):
            # render single char to 8×8 buffer
            buf = bytearray(8)
            fb  = framebuf.FrameBuffer(buf, 8, 8, framebuf.MONO_HLSB)
            fb.fill(0)
            fb.text(ch, 0, 0, 1)
            # scale 2×: each pixel → 2×2 block on OLED
            ox = start_x + i * char_w * scale
            for row in range(8):
                for col in range(8):
                    byte_idx = row
                    bit = (buf[byte_idx] >> (7 - col)) & 1
                    if bit:
                        bx = ox + col * scale
                        by = start_y + row * scale
                        for dy in range(scale):
                            for dx in range(scale):
                                self._px(bx + dx, by + dy, 1)

    # ─────────────────────────────────────────────────────────────────
    #  STATE: SUCCESS
    # ─────────────────────────────────────────────────────────────────
    #
    #  Concept: "Task completed."
    #  Phase 0 (t 0-12): burst lines radiate from centre
    #  Phase 1 (t 4+):   checkmark draws stroke-by-stroke
    #  Phase 2 (t 8+):   two confirmation rings expand outward
    #  Status: inverted bar with msg ("EMAIL SENT", "CHECKED IN"…)
    #
    def draw_success(self, t, msg="DONE"):
        o = self.o
        o.fill(0)

        cx, cy = self.CV_CX, self.CV_CY

        # ── expanding rings ───────────────────────────────────────────
        for i in range(3):
            r = (t * 2 + i * 12) % 28
            if r > 2:
                self._circle(cx, cy, r)

        # ── burst lines (first 16 frames) ────────────────────────────
        if t < 16:
            br = min(t * 2 + 2, 20)
            for i in range(8):
                angle = i * 45
                self._line(cx, cy,
                           _cl(int(cx + br * _c(angle)), 0, self.W-1),
                           _cl(int(cy + br * _s(angle)), self.CV_Y, self.DIV2-1))

        # ── checkmark (draws in over frames 4-16) ────────────────────
        if t >= 4:
            # stroke 1: down-left segment  cx-7,cy → cx-2,cy+6
            p1 = min(1.0, (t - 4) / 6.0)
            ex1 = int(cx - 7 + 5 * p1)
            ey1 = _cl(int(cy + 6 * p1), self.CV_Y, self.DIV2-1)
            self._line(cx - 7, cy, ex1, ey1)
            self._line(cx - 6, cy, ex1, _cl(ey1+1, self.CV_Y, self.DIV2-1))

        if t >= 8:
            # stroke 2: up-right segment  cx-2,cy+6 → cx+9,cy-6
            p2 = min(1.0, (t - 8) / 8.0)
            ex2 = int(cx - 2 + 11 * p2)
            ey2 = _cl(int(cy + 6 - 12 * p2), self.CV_Y, self.DIV2-1)
            self._line(cx - 2, cy + 6, ex2, ey2)
            self._line(cx - 1, _cl(cy+6, self.CV_Y, self.DIV2-1),
                       ex2, _cl(ey2+1, self.CV_Y, self.DIV2-1))

        # ── chrome ────────────────────────────────────────────────────
        self._draw_topbar(t, right_label="DONE")
        self._draw_statusbar(msg, invert=True)
        o.show()

    # ─────────────────────────────────────────────────────────────────
    #  STATE: ERROR
    # ─────────────────────────────────────────────────────────────────
    #
    #  Concept: "Something went wrong — needs attention."
    #  Centre: large "!" — inverts with blink (white→black→white)
    #  Around it: dashed border rect blinks in sync
    #  Bottom of canvas: short error code, left-aligned
    #  Status: full inverted bar with msg, blinks opposite to "!"
    #
    def draw_error(self, t, msg="ERROR"):
        o = self.o
        o.fill(0)

        blink = (t // 6) % 2
        cx, cy = self.CV_CX, self.CV_CY

        # ── central exclamation block ─────────────────────────────────
        block_w, block_h = 22, 32
        bx = cx - block_w // 2
        by = _cl(cy - block_h // 2, self.CV_Y, self.DIV2 - block_h)

        if blink:
            # inverted block
            self._fill_rect_cv(bx, by, block_w, block_h, 1)
            # "!" body
            o.fill_rect(cx - 1, _cl(by + 3, self.CV_Y, self.DIV2-1),
                        3, 17, 0)
            # "!" dot
            o.fill_rect(cx - 1, _cl(by + 23, self.CV_Y, self.DIV2-1),
                        3, 4, 0)
        else:
            # outline block
            o.rect(bx, by, block_w, block_h, 1)
            # "!" body
            o.fill_rect(cx - 1, _cl(by + 3, self.CV_Y, self.DIV2-1),
                        3, 17, 1)
            # "!" dot
            o.fill_rect(cx - 1, _cl(by + 23, self.CV_Y, self.DIV2-1),
                        3, 4, 1)

        # ── dashed outer border (blinks opposite) ────────────────────
        if not blink:
            dash = 6
            for x in range(0, self.W, dash * 2):
                self.o.hline(x, self.CV_Y, dash, 1)
                self.o.hline(x, self.DIV2 - 1, dash, 1)
            for y in range(self.CV_Y, self.DIV2, dash * 2):
                self.o.vline(0, y, dash, 1)
                self.o.vline(self.W - 1, y, dash, 1)

        # ── error code (right of "!", canvas level) ───────────────────
        code = _truncate(msg.upper(), 7)
        ec_x = cx + block_w // 2 + 3
        ec_y = cy - 4
        if ec_x + len(code) * 8 <= self.W and self.CV_Y <= ec_y < self.DIV2 - 8:
            o.text(code, ec_x, ec_y, 1)

        # ── chrome ────────────────────────────────────────────────────
        # topbar inverts on blink to grab attention
        o.fill_rect(0, self.TB_Y, self.W, self.TB_H, blink)
        o.text("OPENCLAW", 1, 1, 1 - blink)
        o.text("ERR", _right_x("ERR", margin=1), 1, 1 - blink)
        o.hline(0, self.DIV1, self.W, 1)

        self._draw_statusbar(msg, invert=not blink)
        o.show()
