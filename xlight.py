#!/usr/bin/env python3
"""
XLight - Cross-Platform Screen Brightness Controller
=====================================================
A compact, professional screen brightness and color temperature
control application that works with ALL monitor types on
Windows, Linux, and macOS.

Dual-engine approach:
  1. Gamma Ramp (Software) - Works on ANY monitor via OS display API
  2. DDC/CI (Hardware)     - Direct monitor control when supported

Author: XLight Team
License: MIT
"""

import sys
import os
import platform
import json
import threading
import math

# ---------------------------------------------------------------------------
# Platform-specific gamma ramp backends
# ---------------------------------------------------------------------------

class GammaBackend:
    """Abstract base for platform-specific gamma ramp manipulation."""
    def get_displays(self):
        raise NotImplementedError
    def set_gamma(self, display_id, brightness, temperature):
        raise NotImplementedError
    def reset_gamma(self, display_id):
        raise NotImplementedError


class WindowsGammaBackend(GammaBackend):
    """Windows gamma control via Win32 GDI SetDeviceGammaRamp.

    Handles multi-monitor setups with mixed monitor types (VGA, HDMI, DP, etc.)
    by creating per-display device contexts via CreateDCW.
    """

    def __init__(self):
        import ctypes
        import ctypes.wintypes
        self.gdi32 = ctypes.windll.gdi32
        self.user32 = ctypes.windll.user32

    def _get_dc(self, display_name=None):
        """Get device context for a specific display.

        Returns (hdc, is_created_dc) tuple. is_created_dc=True means
        caller must use DeleteDC; False means use ReleaseDC.
        """
        if display_name:
            try:
                hdc = self.gdi32.CreateDCW(display_name, None, None, None)
                if hdc:
                    return hdc, True
            except Exception:
                pass
        return self.user32.GetDC(0), False

    def _release_dc(self, hdc, is_created_dc):
        """Release DC using the correct method based on how it was obtained."""
        if is_created_dc:
            self.gdi32.DeleteDC(hdc)
        else:
            self.user32.ReleaseDC(0, hdc)

    def get_displays(self):
        """Enumerate all active display adapters.

        Uses EnumDisplayDevicesW which detects ALL connected monitors
        regardless of connection type (VGA, DVI, HDMI, DP, USB-C, etc.).
        """
        displays = []
        try:
            import ctypes
            import ctypes.wintypes
            class DISPLAY_DEVICE(ctypes.Structure):
                _fields_ = [
                    ('cb', ctypes.wintypes.DWORD),
                    ('DeviceName', ctypes.c_wchar * 32),
                    ('DeviceString', ctypes.c_wchar * 128),
                    ('StateFlags', ctypes.wintypes.DWORD),
                    ('DeviceID', ctypes.c_wchar * 128),
                    ('DeviceKey', ctypes.c_wchar * 128),
                ]
            DISPLAY_DEVICE_ACTIVE = 0x00000001
            dd = DISPLAY_DEVICE()
            dd.cb = ctypes.sizeof(dd)
            i = 0
            while self.user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
                if dd.StateFlags & DISPLAY_DEVICE_ACTIVE:
                    displays.append({
                        'id': dd.DeviceName.rstrip('\x00'),
                        'name': dd.DeviceString.rstrip('\x00'),
                        'index': len(displays),
                    })
                i += 1
        except Exception:
            displays = [{'id': None, 'name': 'Primary Display', 'index': 0}]
        return displays if displays else [{'id': None, 'name': 'Primary Display', 'index': 0}]

    def set_gamma(self, display_id, brightness, temperature):
        """Set gamma ramp for a specific display.

        Works per-monitor even with mixed cable types because gamma
        ramp is set through the display adapter's device context.
        """
        import ctypes
        ramp = (ctypes.c_ushort * 256 * 3)()
        r_mult, g_mult, b_mult = _kelvin_to_rgb_multiplier(temperature)
        for i in range(256):
            val = int(i * 256 * brightness)
            ramp[0][i] = min(65535, int(val * r_mult))
            ramp[1][i] = min(65535, int(val * g_mult))
            ramp[2][i] = min(65535, int(val * b_mult))
        hdc, is_created = self._get_dc(display_id)
        try:
            self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        finally:
            self._release_dc(hdc, is_created)

    def reset_gamma(self, display_id):
        import ctypes
        ramp = (ctypes.c_ushort * 256 * 3)()
        for i in range(256):
            ramp[0][i] = ramp[1][i] = ramp[2][i] = i * 256
        hdc, is_created = self._get_dc(display_id)
        try:
            self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        finally:
            self._release_dc(hdc, is_created)


class LinuxGammaBackend(GammaBackend):
    """Linux gamma control with automatic X11/Wayland detection.

    Fallback chain:
      1. xrandr (X11 sessions — most compatible)
      2. wlr-randr or gammastep (Wayland sessions — sway, hyprland, etc.)
      3. brightnessctl (backlight-based — laptops, works on all sessions)
      4. /sys/class/backlight (raw sysfs — universal laptop fallback)
    """

    def __init__(self):
        self._session = os.environ.get('XDG_SESSION_TYPE', '').lower()
        self._has_xrandr = self._cmd_exists('xrandr')
        self._has_wlr = self._cmd_exists('wlr-randr')
        self._has_brightnessctl = self._cmd_exists('brightnessctl')
        self._backlight_path = self._find_backlight()

    @staticmethod
    def _cmd_exists(name):
        import shutil
        return shutil.which(name) is not None

    @staticmethod
    def _find_backlight():
        """Find sysfs backlight device."""
        bl_dir = '/sys/class/backlight'
        if os.path.isdir(bl_dir):
            for entry in os.listdir(bl_dir):
                path = os.path.join(bl_dir, entry)
                if os.path.isfile(os.path.join(path, 'brightness')):
                    return path
        return None

    def get_displays(self):
        import subprocess
        displays = []

        # X11: use xrandr
        if self._has_xrandr and self._session != 'wayland':
            try:
                result = subprocess.run(['xrandr', '--listmonitors'],
                                        capture_output=True, text=True, timeout=5)
                for line in result.stdout.strip().split('\n')[1:]:
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        name = parts[-1]
                        displays.append({'id': name, 'name': name,
                                         'index': len(displays), 'method': 'xrandr'})
            except Exception:
                pass

        # Wayland: use wlr-randr
        if not displays and self._has_wlr:
            try:
                result = subprocess.run(['wlr-randr'],
                                        capture_output=True, text=True, timeout=5)
                for line in result.stdout.split('\n'):
                    line = line.strip()
                    if line and not line.startswith(' ') and not line.startswith('\t'):
                        # Output name is the first word on non-indented lines
                        name = line.split()[0]
                        if name and not name.startswith('-'):
                            displays.append({'id': name, 'name': name,
                                             'index': len(displays), 'method': 'wlr'})
            except Exception:
                pass

        # Fallback: try xrandr query (X11 on Wayland via XWayland)
        if not displays and self._has_xrandr:
            try:
                result = subprocess.run(['xrandr', '--query'],
                                        capture_output=True, text=True, timeout=5)
                for line in result.stdout.split('\n'):
                    if ' connected' in line:
                        name = line.split()[0]
                        displays.append({'id': name, 'name': name,
                                         'index': len(displays), 'method': 'xrandr'})
            except Exception:
                pass

        # Laptop backlight as final fallback
        if not displays and self._backlight_path:
            bl_name = os.path.basename(self._backlight_path)
            displays.append({'id': bl_name, 'name': f'Laptop ({bl_name})',
                             'index': 0, 'method': 'backlight'})

        if not displays:
            method = 'brightnessctl' if self._has_brightnessctl else 'none'
            displays = [{'id': 'default', 'name': 'Default Display',
                         'index': 0, 'method': method}]

        return displays

    def set_gamma(self, display_id, brightness, temperature):
        import subprocess
        r, g, b = _kelvin_to_rgb_multiplier(temperature)

        # Try xrandr first (X11)
        if self._has_xrandr and self._session != 'wayland':
            target = display_id if display_id and display_id != 'default' else None
            cmd = ['xrandr']
            if target:
                cmd += ['--output', target]
            cmd += ['--brightness', f'{brightness:.2f}',
                    '--gamma', f'{1/max(0.1,brightness*r):.2f}:'
                               f'{1/max(0.1,brightness*g):.2f}:'
                               f'{1/max(0.1,brightness*b):.2f}']
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=5)
                if result.returncode == 0:
                    return
            except Exception:
                pass

        # Try brightnessctl (works on both X11 and Wayland for backlights)
        if self._has_brightnessctl:
            try:
                pct = max(1, int(brightness * 100))
                subprocess.run(['brightnessctl', 'set', f'{pct}%'],
                               capture_output=True, timeout=5)
                return
            except Exception:
                pass

        # Try raw sysfs backlight (laptop fallback)
        if self._backlight_path:
            try:
                max_file = os.path.join(self._backlight_path, 'max_brightness')
                br_file = os.path.join(self._backlight_path, 'brightness')
                with open(max_file, 'r') as f:
                    max_br = int(f.read().strip())
                new_br = max(1, int(max_br * brightness))
                with open(br_file, 'w') as f:
                    f.write(str(new_br))
            except Exception:
                pass

    def reset_gamma(self, display_id):
        import subprocess

        if self._has_xrandr and self._session != 'wayland':
            cmd = ['xrandr']
            if display_id and display_id != 'default':
                cmd += ['--output', display_id]
            cmd += ['--brightness', '1.0', '--gamma', '1.0:1.0:1.0']
            try:
                subprocess.run(cmd, capture_output=True, timeout=5)
            except Exception:
                pass

        if self._has_brightnessctl:
            try:
                subprocess.run(['brightnessctl', 'set', '100%'],
                               capture_output=True, timeout=5)
            except Exception:
                pass


class MacOSGammaBackend(GammaBackend):
    """macOS gamma control via CoreGraphics.

    Supports multi-monitor setups by using CGSetDisplayTransferByTable
    per display ID. Works with all macOS display types including
    built-in Retina, external Thunderbolt/USB-C, HDMI, and DisplayPort.
    """
    def __init__(self):
        import ctypes, ctypes.util
        lib = ctypes.util.find_library('CoreGraphics')
        if not lib:
            raise RuntimeError('CoreGraphics library not found')
        self._cg = ctypes.CDLL(lib)

    def get_displays(self):
        import ctypes
        max_displays = 16
        ids = (ctypes.c_uint32 * max_displays)()
        count = ctypes.c_uint32(0)
        self._cg.CGGetActiveDisplayList(max_displays, ids, ctypes.byref(count))
        displays = [{'id': ids[i], 'name': f'Display {i+1}', 'index': i}
                     for i in range(count.value)]
        return displays if displays else [{'id': 0, 'name': 'Primary Display', 'index': 0}]

    def set_gamma(self, display_id, brightness, temperature):
        import ctypes
        r_m, g_m, b_m = _kelvin_to_rgb_multiplier(temperature)
        n = 256
        rt = (ctypes.c_float * n)()
        gt = (ctypes.c_float * n)()
        bt = (ctypes.c_float * n)()
        for i in range(n):
            v = (i / 255.0) * brightness
            rt[i] = min(1.0, v * r_m)
            gt[i] = min(1.0, v * g_m)
            bt[i] = min(1.0, v * b_m)
        self._cg.CGSetDisplayTransferByTable(
            ctypes.c_uint32(display_id or 0), n, rt, gt, bt)

    def reset_gamma(self, display_id):
        """Reset gamma for a specific display or all displays."""
        if display_id:
            # Per-display reset: set linear gamma ramp
            import ctypes
            n = 256
            table = (ctypes.c_float * n)()
            for i in range(n):
                table[i] = i / 255.0
            self._cg.CGSetDisplayTransferByTable(
                ctypes.c_uint32(display_id), n, table, table, table)
        else:
            # Global reset
            self._cg.CGDisplayRestoreColorSyncSettings()


# ---------------------------------------------------------------------------
# Color temperature
# ---------------------------------------------------------------------------

def _kelvin_to_rgb_multiplier(kelvin):
    """Convert color temperature (Kelvin) to RGB multipliers.
    Based on Tanner Helland's algorithm (f.lux, Redshift, etc.)."""
    kelvin = max(1000, min(10000, kelvin))
    temp = kelvin / 100.0
    if temp <= 66:
        red = 1.0
    else:
        red = 329.698727446 * ((temp - 60) ** -0.1332047592) / 255.0
    if temp <= 66:
        green = (99.4708025861 * math.log(temp) - 161.1195681661) / 255.0
    else:
        green = 288.1221695283 * ((temp - 60) ** -0.0755148492) / 255.0
    if temp >= 66:
        blue = 1.0
    elif temp <= 19:
        blue = 0.0
    else:
        blue = (138.5177312231 * math.log(temp - 10) - 305.0447927307) / 255.0
    return (max(0.0, min(1.0, red)),
            max(0.0, min(1.0, green)),
            max(0.0, min(1.0, blue)))


# ---------------------------------------------------------------------------
# Hardware brightness (DDC/CI)
# ---------------------------------------------------------------------------

class HardwareBrightnessBackend:
    def __init__(self):
        self.available = False
        try:
            import screen_brightness_control as sbc
            self.sbc = sbc
            self.available = True
        except ImportError:
            pass

    def get_displays(self):
        if not self.available:
            return []
        try:
            monitors = self.sbc.list_monitors()
            return [{'id': i, 'name': m, 'index': i} for i, m in enumerate(monitors)]
        except Exception:
            return []

    def get_brightness(self, display_index=None):
        if not self.available:
            return None
        try:
            if display_index is not None:
                return self.sbc.get_brightness(display=display_index)[0]
            return self.sbc.get_brightness()[0]
        except Exception:
            return None

    def set_brightness(self, value, display_index=None):
        if not self.available:
            return False
        try:
            value = max(0, min(100, int(value)))
            if display_index is not None:
                self.sbc.set_brightness(value, display=display_index)
            else:
                self.sbc.set_brightness(value)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def _config_dir():
    system = platform.system()
    if system == 'Windows':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    elif system == 'Darwin':
        base = os.path.join(os.path.expanduser('~'), 'Library', 'Application Support')
    else:
        base = os.environ.get('XDG_CONFIG_HOME',
                              os.path.join(os.path.expanduser('~'), '.config'))
    path = os.path.join(base, 'XLight')
    os.makedirs(path, exist_ok=True)
    return path

def _config_file():
    return os.path.join(_config_dir(), 'settings.json')

DEFAULT_CONFIG = {
    'brightness': 100,
    'temperature': 6500,
    'use_hardware': True,
    'use_gamma': True,
    'profiles': {
        'Day': {'brightness': 100, 'temperature': 6500},
        'Evening': {'brightness': 70, 'temperature': 4500},
        'Night': {'brightness': 40, 'temperature': 3200},
        'Reading': {'brightness': 80, 'temperature': 5500},
    },
    'language': 'en',
}

def load_config():
    path = _config_file()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            merged = {**DEFAULT_CONFIG, **cfg}
            merged['profiles'] = {**DEFAULT_CONFIG['profiles'], **cfg.get('profiles', {})}
            return merged
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(config):
    try:
        with open(_config_file(), 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# i18n
# ---------------------------------------------------------------------------

TRANSLATIONS = {
    'en': {
        'brightness': 'Brightness', 'temperature': 'Color Temperature',
        'profiles': 'Profiles', 'reset': 'Reset',
        'save_profile': 'Save Profile', 'delete_profile': 'Delete',
        'quit': 'Quit', 'show': 'Show',
        'all_displays': 'All Displays', 'profile_name': 'Profile Name:',
        'kelvin': 'K',
    },
    'vi': {
        'brightness': 'Do sang', 'temperature': 'Nhiet do mau',
        'profiles': 'Cau hinh', 'reset': 'Dat lai',
        'save_profile': 'Luu cau hinh', 'delete_profile': 'Xoa',
        'quit': 'Thoat', 'show': 'Hien',
        'all_displays': 'Tat ca man hinh', 'profile_name': 'Ten cau hinh:',
        'kelvin': 'K',
    },
}

def t(key, lang='en'):
    return TRANSLATIONS.get(lang, TRANSLATIONS['en']).get(key, key)


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------

def create_gamma_backend():
    system = platform.system()
    if system == 'Windows':
        return WindowsGammaBackend()
    elif system == 'Darwin':
        return MacOSGammaBackend()
    return LinuxGammaBackend()


# ---------------------------------------------------------------------------
# GUI Application - Compact, Twinkle Tray-inspired design
# ---------------------------------------------------------------------------

import tkinter as tk
from tkinter import ttk, simpledialog

COLORS = {
    'bg': '#ffffff',
    'card_bg': '#f8f8f8',
    'text': '#1a1a1a',
    'text_dim': '#888888',
    'slider_bg': '#e0e0e0',
    'slider_fill': '#0078d4',
    'slider_thumb': '#0078d4',
    'border': '#e8e8e8',
    'footer_bg': '#f0f0f0',
}


class XLightApp:
    """Compact brightness controller - Twinkle Tray style."""

    def __init__(self):
        self.config = load_config()
        self.gamma_backend = create_gamma_backend()
        self.hw_backend = HardwareBrightnessBackend()
        self.lang = self.config.get('language', 'en')
        self._timer = None
        self._building = True

        self._refresh_displays()

        self.root = tk.Tk()
        self.root.title('XLight')
        self.root.configure(bg=COLORS['bg'])
        self.root.resizable(False, False)

        # Compact size matching Twinkle Tray
        n_displays = len(self.displays)
        win_w = 460
        win_h = n_displays * 90 + 44  # display cards + footer
        self.root.geometry(f'{win_w}x{win_h}')

        # Position bottom-right above taskbar (like Twinkle Tray)
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = screen_w - win_w - 16
        y = screen_h - win_h - 60
        self.root.geometry(f'+{x}+{y}')

        # Remove title bar decorations for cleaner look
        self.root.overrideredirect(False)

        try:
            icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.ico')
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
        except Exception:
            pass

        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        self._build_ui()
        self._building = False
        self._apply_all()
        self._setup_tray()

    def _refresh_displays(self):
        gamma_displays = self.gamma_backend.get_displays()
        hw_displays = self.hw_backend.get_displays() if self.hw_backend.available else []
        self.displays = []
        for gd in gamma_displays:
            info = {
                'id': gd['id'], 'name': gd.get('name', f"Display {gd['index']+1}"),
                'index': gd['index'], 'gamma_id': gd['id'],
                'hw_index': None, 'hw_supported': False,
                'brightness': self.config.get('brightness', 100),
            }
            for hd in hw_displays:
                if hd['index'] == gd['index']:
                    info['hw_index'] = hd['index']
                    info['hw_supported'] = True
                    hw_name = hd.get('name', '')
                    if hw_name:
                        hw_name = hw_name.replace('None ', '').strip()
                        if hw_name and hw_name.lower() != 'none':
                            info['name'] = hw_name
                    break
            self.displays.append(info)

    def _build_ui(self):
        """Build Twinkle Tray-style light UI."""
        self.sliders = {}
        self.val_labels = {}
        self.slider_canvases = {}

        main = tk.Frame(self.root, bg=COLORS['bg'])
        main.pack(fill=tk.BOTH, expand=True)

        # ── Per-display cards ──
        for i, d in enumerate(self.displays):
            card = tk.Frame(main, bg=COLORS['bg'])
            card.pack(fill=tk.X, padx=16, pady=(12, 0))

            # Row 1: Icon + Name
            row1 = tk.Frame(card, bg=COLORS['bg'])
            row1.pack(fill=tk.X, pady=(0, 6))

            tk.Label(row1, text='\U0001F5B5', bg=COLORS['bg'], fg=COLORS['text_dim'],
                     font=('Segoe UI', 13)).pack(side=tk.LEFT, padx=(0, 8))

            tk.Label(row1, text=d['name'], bg=COLORS['bg'], fg=COLORS['text'],
                     font=('Segoe UI', 11)).pack(side=tk.LEFT)

            # Row 2: Slider + Value
            row2 = tk.Frame(card, bg=COLORS['bg'])
            row2.pack(fill=tk.X)

            # Value label on the right
            vl = tk.Label(row2, text=str(d['brightness']),
                          bg=COLORS['bg'], fg=COLORS['text'],
                          font=('Segoe UI', 14, 'bold'), width=4, anchor='e')
            vl.pack(side=tk.RIGHT, padx=(12, 0))
            self.val_labels[i] = vl

            # Custom canvas slider
            canvas = tk.Canvas(row2, height=20, bg=COLORS['bg'],
                               highlightthickness=0, cursor='hand2')
            canvas.pack(side=tk.LEFT, fill=tk.X, expand=True)
            self.slider_canvases[i] = canvas

            # Store slider data
            self.sliders[i] = {
                'canvas': canvas,
                'value': d['brightness'],
                'dragging': False,
            }

            # Bind mouse events
            canvas.bind('<Configure>', lambda e, idx=i: self._draw_slider(idx))
            canvas.bind('<Button-1>', lambda e, idx=i: self._slider_press(e, idx))
            canvas.bind('<B1-Motion>', lambda e, idx=i: self._slider_drag(e, idx))
            canvas.bind('<ButtonRelease-1>', lambda e, idx=i: self._slider_release(e, idx))

            # Separator line between displays (not after last)
            if i < len(self.displays) - 1:
                tk.Frame(main, bg=COLORS['border'], height=1).pack(fill=tk.X, padx=16, pady=(12, 0))

        # ── Footer ──
        footer = tk.Frame(main, bg=COLORS['footer_bg'], height=44)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.pack_propagate(False)

        tk.Label(footer, text='Adjust Brightness', bg=COLORS['footer_bg'],
                 fg=COLORS['text_dim'], font=('Segoe UI', 10)).pack(
                     side=tk.LEFT, padx=(16, 0), pady=10)

        # Footer icons (right side)
        icon_frame = tk.Frame(footer, bg=COLORS['footer_bg'])
        icon_frame.pack(side=tk.RIGHT, padx=(0, 12), pady=8)

        # Settings icon
        tk.Button(icon_frame, text='\u2699', bg=COLORS['footer_bg'],
                  fg=COLORS['text_dim'], font=('Segoe UI', 14),
                  relief=tk.FLAT, padx=4, pady=0, cursor='hand2',
                  activebackground=COLORS['footer_bg'],
                  command=self._show_settings).pack(side=tk.RIGHT)

        # Reset icon
        tk.Button(icon_frame, text='\u21BA', bg=COLORS['footer_bg'],
                  fg=COLORS['text_dim'], font=('Segoe UI', 14),
                  relief=tk.FLAT, padx=4, pady=0, cursor='hand2',
                  activebackground=COLORS['footer_bg'],
                  command=self._reset_all).pack(side=tk.RIGHT)

    def _draw_slider(self, idx):
        """Draw a custom blue slider on canvas."""
        canvas = self.sliders[idx]['canvas']
        value = self.sliders[idx]['value']
        canvas.delete('all')

        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1:
            return

        # Track dimensions
        track_h = 4
        track_y = h // 2
        thumb_r = 7
        pad = thumb_r + 2

        # Slider position
        pct = (value - 5) / 95.0  # 5-100 range
        fill_x = pad + pct * (w - 2 * pad)

        # Background track
        canvas.create_round_rect = None  # use line for simplicity
        canvas.create_line(pad, track_y, w - pad, track_y,
                           fill=COLORS['slider_bg'], width=track_h, capstyle='round')

        # Filled track
        if fill_x > pad:
            canvas.create_line(pad, track_y, fill_x, track_y,
                               fill=COLORS['slider_fill'], width=track_h, capstyle='round')

        # Thumb circle
        canvas.create_oval(fill_x - thumb_r, track_y - thumb_r,
                           fill_x + thumb_r, track_y + thumb_r,
                           fill=COLORS['slider_thumb'], outline='')

    def _slider_pos_to_value(self, x, idx):
        """Convert canvas x position to slider value (5-100)."""
        canvas = self.sliders[idx]['canvas']
        w = canvas.winfo_width()
        pad = 9
        pct = (x - pad) / max(1, w - 2 * pad)
        pct = max(0.0, min(1.0, pct))
        return int(5 + pct * 95)

    def _slider_press(self, event, idx):
        self.sliders[idx]['dragging'] = True
        val = self._slider_pos_to_value(event.x, idx)
        self._update_slider(idx, val)

    def _slider_drag(self, event, idx):
        if self.sliders[idx]['dragging']:
            val = self._slider_pos_to_value(event.x, idx)
            self._update_slider(idx, val)

    def _slider_release(self, event, idx):
        self.sliders[idx]['dragging'] = False

    def _update_slider(self, idx, val):
        """Update slider value, label, and trigger brightness change."""
        self.sliders[idx]['value'] = val
        self.val_labels[idx].config(text=str(val))
        self.displays[idx]['brightness'] = val
        self._draw_slider(idx)
        if not self._building:
            self._debounce()

    def _show_settings(self):
        """Show settings popup for profiles and modes."""
        popup = tk.Toplevel(self.root)
        popup.title('XLight Settings')
        popup.configure(bg=COLORS['bg'])
        popup.geometry('320x300')
        popup.transient(self.root)
        popup.grab_set()

        # Profiles section
        tk.Label(popup, text='Profiles', bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Segoe UI', 11, 'bold')).pack(anchor='w', padx=16, pady=(12, 8))

        for name in self.config.get('profiles', {}):
            btn_frame = tk.Frame(popup, bg=COLORS['bg'])
            btn_frame.pack(fill=tk.X, padx=16, pady=2)
            tk.Button(btn_frame, text=name, bg=COLORS['card_bg'], fg=COLORS['text'],
                      font=('Segoe UI', 10), relief=tk.FLAT, padx=12, pady=4,
                      cursor='hand2', anchor='w',
                      command=lambda n=name, p=popup: (self._apply_profile(n), p.destroy())
                      ).pack(fill=tk.X)

        # Save profile button
        tk.Button(popup, text='+ Save Current as Profile', bg=COLORS['slider_fill'],
                  fg='white', font=('Segoe UI', 10), relief=tk.FLAT,
                  padx=12, pady=6, cursor='hand2',
                  command=lambda: (popup.destroy(), self._save_profile())
                  ).pack(fill=tk.X, padx=16, pady=(12, 4))

        # Separator
        tk.Frame(popup, bg=COLORS['border'], height=1).pack(fill=tk.X, padx=16, pady=8)

        # Mode toggles
        tk.Label(popup, text='Brightness Mode', bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Segoe UI', 11, 'bold')).pack(anchor='w', padx=16, pady=(0, 8))

        self.use_gamma = tk.BooleanVar(value=self.config.get('use_gamma', True))
        self.use_hw = tk.BooleanVar(value=self.config.get('use_hardware', True))

        tk.Checkbutton(popup, text='Software (Gamma Ramp)', variable=self.use_gamma,
                       bg=COLORS['bg'], fg=COLORS['text'], font=('Segoe UI', 10),
                       selectcolor=COLORS['card_bg'], activebackground=COLORS['bg'],
                       command=self._on_mode).pack(anchor='w', padx=16)
        hw_cb = tk.Checkbutton(popup, text='Hardware (DDC/CI)', variable=self.use_hw,
                               bg=COLORS['bg'], fg=COLORS['text'], font=('Segoe UI', 10),
                               selectcolor=COLORS['card_bg'], activebackground=COLORS['bg'],
                               command=self._on_mode)
        hw_cb.pack(anchor='w', padx=16)
        if not self.hw_backend.available:
            self.use_hw.set(False)
            hw_cb.configure(state='disabled')

        # Color temperature
        tk.Frame(popup, bg=COLORS['border'], height=1).pack(fill=tk.X, padx=16, pady=8)
        tk.Label(popup, text='Color Temperature', bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Segoe UI', 11, 'bold')).pack(anchor='w', padx=16, pady=(0, 4))

        temp_frame = tk.Frame(popup, bg=COLORS['bg'])
        temp_frame.pack(fill=tk.X, padx=16)

        self.temp_label = tk.Label(temp_frame, text=f"{self.config['temperature']}K",
                                   bg=COLORS['bg'], fg=COLORS['text'],
                                   font=('Segoe UI', 10, 'bold'), width=6, anchor='e')
        self.temp_label.pack(side=tk.RIGHT)

        self.temp_var = tk.IntVar(value=self.config['temperature'])
        style = ttk.Style()
        style.configure('Temp.Horizontal.TScale', background=COLORS['bg'],
                        troughcolor=COLORS['slider_bg'], sliderthickness=14, sliderlength=14)
        temp_sl = ttk.Scale(temp_frame, from_=1000, to=10000,
                            variable=self.temp_var, orient=tk.HORIZONTAL,
                            style='Temp.Horizontal.TScale',
                            command=self._on_temp)
        temp_sl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

    # ── Event handlers ──

    def _on_temp(self, value):
        val = int(float(value))
        self.temp_label.config(text=f'{val}K')
        self.config['temperature'] = val
        if not self._building:
            self._debounce()

    def _on_mode(self):
        self.config['use_gamma'] = self.use_gamma.get()
        self.config['use_hardware'] = self.use_hw.get()
        self._apply_all()

    def _debounce(self):
        if self._timer is not None:
            self.root.after_cancel(self._timer)
        self._timer = self.root.after(50, self._apply_all)

    def _apply_all(self):
        temperature = self.config['temperature']
        use_gamma = self.config.get('use_gamma', True)
        use_hw = self.config.get('use_hardware', True)

        for d in self.displays:
            brightness = d.get('brightness', 100) / 100.0
            if use_gamma:
                try:
                    self.gamma_backend.set_gamma(d['gamma_id'], brightness, temperature)
                except Exception:
                    pass
            if use_hw and d.get('hw_supported') and d.get('hw_index') is not None:
                try:
                    self.hw_backend.set_brightness(int(brightness * 100), d['hw_index'])
                except Exception:
                    pass

        # Update config with average brightness
        if self.displays:
            self.config['brightness'] = self.displays[0]['brightness']
        save_config(self.config)

    def _apply_profile(self, name):
        profiles = self.config.get('profiles', {})
        if name not in profiles:
            return
        p = profiles[name]
        b = p.get('brightness', 100)
        t_val = p.get('temperature', 6500)
        for i in range(len(self.displays)):
            self._update_slider(i, b)
        if hasattr(self, 'temp_var'):
            self.temp_var.set(t_val)
            self._on_temp(str(t_val))

    def _save_profile(self):
        name = simpledialog.askstring(t('save_profile', self.lang),
                                      t('profile_name', self.lang),
                                      parent=self.root)
        if name and name.strip():
            name = name.strip()
            self.config.setdefault('profiles', {})
            avg_b = sum(d['brightness'] for d in self.displays) // max(1, len(self.displays))
            self.config['profiles'][name] = {
                'brightness': avg_b,
                'temperature': self.config['temperature'],
            }
            save_config(self.config)

    def _reset_all(self):
        for i in range(len(self.displays)):
            self._update_slider(i, 100)
        if hasattr(self, 'temp_var'):
            self.temp_var.set(6500)
            self._on_temp('6500')
        for d in self.displays:
            try:
                self.gamma_backend.reset_gamma(d['gamma_id'])
            except Exception:
                pass
        self.config['brightness'] = 100
        self.config['temperature'] = 6500
        save_config(self.config)

    def _on_close(self):
        if self._tray_icon:
            self.root.withdraw()
        else:
            self._exit()

    def _exit(self):
        for d in self.displays:
            try:
                self.gamma_backend.reset_gamma(d['gamma_id'])
            except Exception:
                pass
        save_config(self.config)
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        self.root.quit()
        self.root.destroy()

    # ── System Tray ──

    def _setup_tray(self):
        self._tray_icon = None
        try:
            import pystray
            from PIL import Image, ImageDraw
            img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.ellipse([16, 16, 48, 48], fill=(124, 106, 239, 255))
            for angle in range(0, 360, 45):
                rad = math.radians(angle)
                x1, y1 = 32 + 18*math.cos(rad), 32 + 18*math.sin(rad)
                x2, y2 = 32 + 28*math.cos(rad), 32 + 28*math.sin(rad)
                draw.line([(x1,y1),(x2,y2)], fill=(124,106,239,200), width=3)
            menu = pystray.Menu(
                pystray.MenuItem(t('show', self.lang),
                                 lambda: self.root.after(0, self.root.deiconify)),
                pystray.MenuItem(t('reset', self.lang), lambda: self._reset_all()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(t('quit', self.lang),
                                 lambda: self.root.after(0, self._exit)),
            )
            self._tray_icon = pystray.Icon('XLight', img, 'XLight', menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------------
# CLI fallback
# ---------------------------------------------------------------------------

def run_cli():
    print("XLight v1.0 - CLI Mode")
    print("=" * 40)
    gamma = create_gamma_backend()
    hw = HardwareBrightnessBackend()
    config = load_config()
    displays = gamma.get_displays()
    print(f"\nDetected {len(displays)} display(s):")
    for i, d in enumerate(displays):
        print(f"  [{i}] {d['name']}")
    if hw.available:
        print(f"\nHardware brightness: Available")
    print(f"\nCommands: b <5-100>, t <1000-10000>, r (reset), q (quit)")
    while True:
        try:
            cmd = input("\nXLight> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not cmd:
            continue
        parts = cmd.split()
        action = parts[0].lower()
        if action == 'q':
            break
        elif action == 'r':
            for d in displays:
                gamma.reset_gamma(d['id'])
            print("Reset.")
        elif action == 'b' and len(parts) > 1:
            try:
                val = max(5, min(100, int(parts[1])))
                for d in displays:
                    gamma.set_gamma(d['id'], val/100.0, config.get('temperature', 6500))
                if hw.available:
                    hw.set_brightness(val)
                config['brightness'] = val
                save_config(config)
                print(f"Brightness: {val}%")
            except ValueError:
                print("Invalid. Use: b <5-100>")
        elif action == 't' and len(parts) > 1:
            try:
                val = max(1000, min(10000, int(parts[1])))
                for d in displays:
                    gamma.set_gamma(d['id'], config.get('brightness',100)/100.0, val)
                config['temperature'] = val
                save_config(config)
                print(f"Temperature: {val}K")
            except ValueError:
                print("Invalid. Use: t <1000-10000>")
        else:
            print("Unknown. Use b, t, r, or q.")
    for d in displays:
        gamma.reset_gamma(d['id'])


def main():
    if '--cli' in sys.argv:
        run_cli()
        return
    try:
        app = XLightApp()
        app.run()
    except Exception:
        print("No display. Falling back to CLI.")
        run_cli()


if __name__ == '__main__':
    main()
