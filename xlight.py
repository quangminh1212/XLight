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

    Note: Windows Vista+ rejects gamma ramps that darken any channel below ~50%
    of the linear identity white-point. We work around this by:
      - linear scale for brightness 50–100%
      - fixed 50% white-point + steeper midtone gamma for brightness <50%
      - clamping color-temp multipliers so every channel stays accepted
    """

    # Windows security floor: white-point per channel must stay >= ~50%
    _WP_FLOOR = 0.5
    _MIN_BRIGHTNESS = 0.05

    def __init__(self):
        import ctypes
        import ctypes.wintypes
        self.gdi32 = ctypes.windll.gdi32
        self.user32 = ctypes.windll.user32

    def _get_dc(self, display_name=None):
        """Get device context for a specific display.

        Prefer CreateDCW(device_name) — GetDC(0) often fails with
        SetDeviceGammaRamp on multi-GPU / multi-monitor systems.
        Returns (hdc, is_created_dc).
        """
        if display_name:
            try:
                hdc = self.gdi32.CreateDCW(display_name, None, None, None)
                if hdc:
                    return hdc, True
            except Exception:
                pass
        # Fallback: first active display via CreateDCW (not GetDC — unreliable)
        for d in self.get_displays():
            if d.get('id'):
                try:
                    hdc = self.gdi32.CreateDCW(d['id'], None, None, None)
                    if hdc:
                        return hdc, True
                except Exception:
                    pass
        hdc = self.user32.GetDC(0)
        return hdc, False

    def _release_dc(self, hdc, is_created_dc):
        """Release DC using the correct method based on how it was obtained."""
        if not hdc:
            return
        if is_created_dc:
            self.gdi32.DeleteDC(hdc)
        else:
            self.user32.ReleaseDC(0, hdc)

    def get_displays(self):
        """Enumerate all active display adapters.

        Uses EnumDisplayDevicesW which detects ALL connected monitors
        regardless of connection type (VGA, DVI, HDMI, DP, USB-C, etc.).
        Prefers the attached monitor's friendly name over the adapter string.
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
                    adapter_name = dd.DeviceName.rstrip('\x00')
                    adapter_str = dd.DeviceString.rstrip('\x00')
                    # Prefer attached monitor friendly name
                    mon_name = adapter_str
                    try:
                        md = DISPLAY_DEVICE()
                        md.cb = ctypes.sizeof(md)
                        if self.user32.EnumDisplayDevicesW(adapter_name, 0, ctypes.byref(md), 0):
                            mstr = md.DeviceString.rstrip('\x00')
                            if mstr and mstr.lower() not in ('', 'generic pnp monitor'):
                                mon_name = mstr
                            elif mstr:
                                mon_name = mstr
                    except Exception:
                        pass
                    displays.append({
                        'id': adapter_name,
                        'name': mon_name or adapter_str or f'Display {len(displays)+1}',
                        'index': len(displays),
                    })
                i += 1
        except Exception:
            displays = [{'id': None, 'name': 'Primary Display', 'index': 0}]
        return displays if displays else [{'id': None, 'name': 'Primary Display', 'index': 0}]

    def _channel_value(self, index, brightness, mult):
        """Compute one gamma-ramp entry compatible with Windows floor rules.

        Prefer linear scale so software brightness % tracks the label:
          br >= 50% → pure linear scale (1:1 with slider)
          br < 50%  → white-point held at 50% + extra midtone gamma
                      (Windows rejects darker white-points)
        """
        n = index / 255.0
        br = max(self._MIN_BRIGHTNESS, min(1.0, float(brightness)))
        m = max(0.0, min(1.0, float(mult)))

        if br >= self._WP_FLOOR:
            # 50–100%: linear — 80% looks ~80%
            scale = br
            power = 1.0
        else:
            # Below 50%: OS floor on white-point; darken midtones only
            scale = self._WP_FLOOR
            t = (br - self._MIN_BRIGHTNESS) / (self._WP_FLOOR - self._MIN_BRIGHTNESS)
            t = max(0.0, min(1.0, t))
            power = min(2.05, 1.0 + (1.0 - t) * 1.05)

        floor_m = min(1.0, self._WP_FLOOR / max(scale, 1e-6))
        m_eff = max(m, floor_m)
        return min(65535, int(round((n ** power) * scale * m_eff * 65535.0)))

    def _build_ramp(self, brightness, temperature):
        import ctypes
        ramp = (ctypes.c_ushort * 256 * 3)()
        r_mult, g_mult, b_mult = _kelvin_to_rgb_multiplier(temperature)
        for i in range(256):
            ramp[0][i] = self._channel_value(i, brightness, r_mult)
            ramp[1][i] = self._channel_value(i, brightness, g_mult)
            ramp[2][i] = self._channel_value(i, brightness, b_mult)
        return ramp

    def set_gamma(self, display_id, brightness, temperature):
        """Set gamma ramp for a specific display.

        Works per-monitor even with mixed cable types because gamma
        ramp is set through the display adapter's device context.
        Returns True if the OS accepted the ramp.
        """
        import ctypes
        ramp = self._build_ramp(brightness, temperature)
        hdc, is_created = self._get_dc(display_id)
        try:
            if not hdc:
                return False
            return bool(self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
        finally:
            self._release_dc(hdc, is_created)

    def reset_gamma(self, display_id):
        import ctypes
        ramp = (ctypes.c_ushort * 256 * 3)()
        for i in range(256):
            # Identity: i*256 is accepted; also matches historical GDI convention
            ramp[0][i] = ramp[1][i] = ramp[2][i] = i * 256
        hdc, is_created = self._get_dc(display_id)
        try:
            if not hdc:
                return False
            return bool(self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
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
                pct = max(0, int(brightness * 100))
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
                new_br = max(0, int(max_br * brightness))
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
            value = max(0, min(100, int(round(value))))
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

# XLab Web design tokens (tailwind.config.js + globals.css) — exact brand colors
COLORS = {
    'bg': '#FFFFFF',
    'bg_secondary': '#F9FAFB',      # gray-50
    'bg_tertiary': '#F3F4F6',       # gray-100
    'card_bg': '#FFFFFF',
    'text': '#111827',              # gray-900
    'text_secondary': '#4B5563',    # gray-600
    'text_dim': '#6B7280',          # gray-500
    'text_muted': '#9CA3AF',        # gray-400
    'primary': '#00A19A',           # xlab / primary-500
    'primary_dark': '#00726A',
    'primary_light': '#33D6D6',
    'primary_50': '#F0FDFC',
    'primary_100': '#CCFBF1',
    'primary_600': '#0D9488',
    'secondary': '#37C88F',
    'slider_bg': '#E5E7EB',         # gray-200
    'slider_fill': '#00A19A',
    'slider_thumb': '#00A19A',
    'border': '#E5E7EB',            # gray-200
    'border_strong': '#D1D5DB',     # gray-300
    'footer_bg': '#F9FAFB',
    'header_bg': '#FFFFFF',
    'white': '#FFFFFF',
    'error': '#EF4444',
}

FONT_UI = ('Segoe UI', 10)
FONT_UI_MD = ('Segoe UI', 11)
FONT_UI_BOLD = ('Segoe UI', 11, 'bold')
FONT_TITLE = ('Segoe UI', 13, 'bold')
FONT_VALUE = ('Segoe UI', 14, 'bold')
FONT_SECTION = ('Segoe UI', 11, 'bold')
FONT_SMALL = ('Segoe UI', 9)


def _app_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _logo_path():
    return os.path.join(_app_dir(), 'logo.png')


def _icon_ico_path():
    return os.path.join(_app_dir(), 'icon.ico')


def create_app_icon(size=64):
    """Build square tray/window icon from XLab Web logo.png.

    Wide wordmark is letterboxed on a white rounded plate so it stays
    readable on dark Windows taskbars.
    """
    from PIL import Image, ImageDraw

    logo_file = _logo_path()
    if not os.path.isfile(logo_file):
        # Minimal fallback if asset is missing
        img = Image.new('RGBA', (size, size), (0, 161, 154, 255))
        return img

    logo = Image.open(logo_file).convert('RGBA')
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)

    canvas = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    plate = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(plate)
    radius = max(2, size // 6)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius,
                           fill=(255, 255, 255, 255))
    canvas.alpha_composite(plate)

    pad = 0.12
    max_w = int(size * (1 - 2 * pad))
    max_h = int(size * (1 - 2 * pad))
    lw, lh = logo.size
    scale = min(max_w / max(1, lw), max_h / max(1, lh))
    nw = max(1, int(lw * scale))
    nh = max(1, int(lh * scale))
    resized = logo.resize((nw, nh), Image.Resampling.LANCZOS)
    x = (size - nw) // 2
    y = (size - nh) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas


class XLightApp:
    """Compact brightness controller — XLab Web visual language."""

    def __init__(self):
        self.config = load_config()
        self.gamma_backend = create_gamma_backend()
        self.hw_backend = HardwareBrightnessBackend()
        self.lang = self.config.get('language', 'en')
        self._timer = None
        self._save_timer = None
        self._hw_timer = None
        self._building = True
        self._logo_photo = None
        self._icon_photo = None

        self._refresh_displays()

        self.root = tk.Tk()
        self.root.title('XLight · XLab')
        self.root.configure(bg=COLORS['bg_secondary'])
        self.root.resizable(False, False)

        # Header + per-display cards + footer
        n_displays = len(self.displays)
        win_w = 480
        win_h = 56 + n_displays * 108 + 48
        self.root.geometry(f'{win_w}x{win_h}')

        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - win_w) // 2
        y = (screen_h - win_h) // 2
        self.root.geometry(f'+{x}+{y}')

        self.root.overrideredirect(False)
        self._set_window_icon()
        self.root.protocol('WM_DELETE_WINDOW', self._on_close)

        self._build_ui()
        self._building = False
        self._apply_all()
        self._setup_tray()

    def _refresh_displays(self):
        gamma_displays = self.gamma_backend.get_displays()
        hw_displays = self.hw_backend.get_displays() if self.hw_backend.available else []
        cfg_br = max(5, min(100, int(self.config.get('brightness', 100))))
        self.displays = []
        used_hw = set()
        for gd in gamma_displays:
            info = {
                'id': gd['id'], 'name': gd.get('name', f"Display {gd['index']+1}"),
                'index': gd['index'], 'gamma_id': gd['id'],
                'hw_index': None, 'hw_supported': False,
                'brightness': cfg_br,
            }
            # Prefer index match; fall back to first unused HW monitor
            matched = None
            for hd in hw_displays:
                if hd['index'] == gd['index'] and hd['index'] not in used_hw:
                    matched = hd
                    break
            if matched is None:
                for hd in hw_displays:
                    if hd['index'] not in used_hw:
                        matched = hd
                        break
            if matched is not None:
                used_hw.add(matched['index'])
                info['hw_index'] = matched['index']
                info['hw_supported'] = True
                hw_name = (matched.get('name') or '').replace('None ', '').strip()
                if hw_name and hw_name.lower() not in ('none', 'generic pnp monitor',
                                                       'generic monitor'):
                    info['name'] = hw_name
                # Prefer live hardware brightness when available
                try:
                    cur = self.hw_backend.get_brightness(matched['index'])
                    if cur is not None:
                        info['brightness'] = max(5, min(100, int(cur)))
                except Exception:
                    pass
            self.displays.append(info)

    def _build_ui(self):
        """Build XLab Web–styled UI: white header, soft gray canvas, teal accents."""
        self.sliders = {}
        self.val_labels = {}
        self.slider_canvases = {}
        self.badge_labels = {}

        outer = tk.Frame(self.root, bg=COLORS['bg_secondary'])
        outer.pack(fill=tk.BOTH, expand=True)

        # ── Header (XLab sticky header style) ──
        header = tk.Frame(outer, bg=COLORS['header_bg'], height=52)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        header_inner = tk.Frame(header, bg=COLORS['header_bg'])
        header_inner.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        brand = tk.Frame(header_inner, bg=COLORS['header_bg'])
        brand.pack(side=tk.LEFT, fill=tk.Y)

        # Logo mark from logo.png (XLab wordmark scaled for header)
        try:
            from PIL import Image, ImageTk
            if os.path.isfile(_logo_path()):
                logo_img = Image.open(_logo_path()).convert('RGBA')
                bb = logo_img.getbbox()
                if bb:
                    logo_img = logo_img.crop(bb)
                h = 28
                scale = h / max(1, logo_img.height)
                w = max(1, int(logo_img.width * scale))
                logo_img = logo_img.resize((w, h), Image.Resampling.LANCZOS)
                self._logo_photo = ImageTk.PhotoImage(logo_img)
                tk.Label(brand, image=self._logo_photo, bg=COLORS['header_bg']).pack(
                    side=tk.LEFT, padx=(0, 10))
        except Exception:
            tk.Label(brand, text='XLab', bg=COLORS['header_bg'], fg=COLORS['primary'],
                     font=FONT_TITLE).pack(side=tk.LEFT, padx=(0, 8))

        # Vertical divider + product name
        tk.Frame(brand, bg=COLORS['border'], width=1).pack(side=tk.LEFT, fill=tk.Y,
                                                          padx=(0, 10), pady=4)
        title_col = tk.Frame(brand, bg=COLORS['header_bg'])
        title_col.pack(side=tk.LEFT)
        tk.Label(title_col, text='XLight', bg=COLORS['header_bg'], fg=COLORS['text'],
                 font=FONT_TITLE).pack(anchor='w')
        tk.Label(title_col, text='Brightness Control', bg=COLORS['header_bg'],
                 fg=COLORS['text_dim'], font=FONT_SMALL).pack(anchor='w')

        # Header actions — Segoe MDL2 outline icons (not emoji)
        actions = tk.Frame(header_inner, bg=COLORS['header_bg'])
        actions.pack(side=tk.RIGHT)
        # E72C = Refresh, E713 = Settings gear (bánh răng)
        self._icon_btn(actions, '\uE72C', self._reset_all).pack(side=tk.RIGHT, padx=(4, 0))
        self._icon_btn(actions, '\uE713', self._show_settings).pack(side=tk.RIGHT)

        # Header bottom border (teal-tinted subtle line like XLab)
        tk.Frame(outer, bg=COLORS['border'], height=1).pack(fill=tk.X)
        tk.Frame(outer, bg=COLORS['primary'], height=2).pack(fill=tk.X)

        # ── Content ──
        main = tk.Frame(outer, bg=COLORS['bg_secondary'])
        main.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

        for i, d in enumerate(self.displays):
            # Card: white surface, gray border (XLab card)
            card_wrap = tk.Frame(main, bg=COLORS['border'], padx=1, pady=1)
            card_wrap.pack(fill=tk.X, pady=(0, 10) if i < len(self.displays) - 1 else 0)
            card = tk.Frame(card_wrap, bg=COLORS['card_bg'])
            card.pack(fill=tk.BOTH, expand=True)

            pad = tk.Frame(card, bg=COLORS['card_bg'])
            pad.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

            # Row 1: accent chip + name + HW badge
            row1 = tk.Frame(pad, bg=COLORS['card_bg'])
            row1.pack(fill=tk.X, pady=(0, 10))

            chip = tk.Label(row1, text='  ', bg=COLORS['primary'], width=1,
                            font=('Segoe UI', 8))
            chip.pack(side=tk.LEFT, padx=(0, 8), ipady=6)

            name_col = tk.Frame(row1, bg=COLORS['card_bg'])
            name_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(name_col, text=d['name'], bg=COLORS['card_bg'], fg=COLORS['text'],
                     font=FONT_UI_BOLD, anchor='w').pack(anchor='w')
            status = 'DDC/CI' if d.get('hw_supported') else 'Gamma'
            tk.Label(name_col, text=status, bg=COLORS['card_bg'], fg=COLORS['primary'],
                     font=FONT_SMALL, anchor='w').pack(anchor='w')

            # Value badge (teal soft chip)
            badge = tk.Label(row1, text=f"  {d['brightness']}%  ",
                             bg=COLORS['primary_50'], fg=COLORS['primary_600'],
                             font=FONT_UI_BOLD)
            badge.pack(side=tk.RIGHT)
            self.badge_labels[i] = badge
            self.val_labels[i] = badge

            # Row 2: slider
            row2 = tk.Frame(pad, bg=COLORS['card_bg'])
            row2.pack(fill=tk.X)
            row2.columnconfigure(0, weight=1)

            canvas = tk.Canvas(row2, height=22, bg=COLORS['card_bg'],
                               highlightthickness=0, cursor='hand2')
            canvas.grid(row=0, column=0, sticky='ew')
            self.slider_canvases[i] = canvas
            self.sliders[i] = {
                'canvas': canvas,
                'value': d['brightness'],
                'dragging': False,
            }
            canvas.bind('<Configure>', lambda e, idx=i: self._draw_slider(idx))
            canvas.bind('<Button-1>', lambda e, idx=i: self._slider_press(e, idx))
            canvas.bind('<B1-Motion>', lambda e, idx=i: self._slider_drag(e, idx))
            canvas.bind('<ButtonRelease-1>', lambda e, idx=i: self._slider_release(e, idx))

        # ── Footer ──
        footer = tk.Frame(outer, bg=COLORS['footer_bg'], height=44)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        footer.pack_propagate(False)
        tk.Frame(footer, bg=COLORS['border'], height=1).pack(fill=tk.X)

        foot_inner = tk.Frame(footer, bg=COLORS['footer_bg'])
        foot_inner.pack(fill=tk.BOTH, expand=True, padx=16)
        tk.Label(foot_inner, text='XLab  ·  Adjust brightness per display',
                 bg=COLORS['footer_bg'], fg=COLORS['text_dim'],
                 font=FONT_SMALL).pack(side=tk.LEFT, pady=12)
        tk.Label(foot_inner, text='5–100%', bg=COLORS['footer_bg'],
                 fg=COLORS['primary'], font=FONT_SMALL).pack(side=tk.RIGHT, pady=12)

    def _ghost_btn(self, parent, text, command):
        """XLab-style ghost text/icon button (teal on hover)."""
        return tk.Button(
            parent, text=text, command=command,
            bg=COLORS['header_bg'], fg=COLORS['text_secondary'],
            activebackground=COLORS['primary_50'], activeforeground=COLORS['primary'],
            font=('Segoe UI', 13), relief=tk.FLAT, bd=0, padx=8, pady=2,
            cursor='hand2', highlightthickness=0,
        )

    def _icon_btn(self, parent, glyph, command):
        """Windows outline icon (Segoe MDL2) — monochrome bánh răng / refresh, not emoji."""
        return tk.Button(
            parent, text=glyph, command=command,
            bg=COLORS['header_bg'], fg=COLORS['text_secondary'],
            activebackground=COLORS['primary_50'],
            activeforeground=COLORS['primary'],
            font=('Segoe MDL2 Assets', 15), relief=tk.FLAT, bd=0, padx=8, pady=2,
            cursor='hand2', highlightthickness=0,
        )

    def _primary_btn(self, parent, text, command, **pack_kw):
        btn = tk.Button(
            parent, text=text, command=command,
            bg=COLORS['primary'], fg=COLORS['white'],
            activebackground=COLORS['primary_600'], activeforeground=COLORS['white'],
            font=FONT_UI, relief=tk.FLAT, bd=0, padx=14, pady=8,
            cursor='hand2', highlightthickness=0,
        )
        return btn

    def _outline_btn(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command,
            bg=COLORS['bg'], fg=COLORS['text'],
            activebackground=COLORS['primary_50'], activeforeground=COLORS['primary'],
            font=FONT_UI, relief=tk.FLAT, bd=0, padx=12, pady=6,
            cursor='hand2', highlightthickness=1,
            highlightbackground=COLORS['border'], highlightcolor=COLORS['primary'],
        )

    def _draw_slider(self, idx):
        """Draw XLab teal slider track + thumb."""
        if idx not in self.sliders:
            return
        canvas = self.sliders[idx]['canvas']
        value = self.sliders[idx]['value']
        canvas.delete('all')

        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w <= 1:
            return

        track_h = 6
        track_y = h // 2
        thumb_r = 8
        pad = thumb_r + 2

        # value range 5–100
        pct = (max(5, min(100, value)) - 5) / 95.0
        fill_x = pad + pct * (w - 2 * pad)

        canvas.create_line(pad, track_y, w - pad, track_y,
                           fill=COLORS['slider_bg'], width=track_h, capstyle='round')
        if fill_x > pad:
            canvas.create_line(pad, track_y, fill_x, track_y,
                               fill=COLORS['slider_fill'], width=track_h, capstyle='round')
        canvas.create_oval(fill_x - thumb_r, track_y - thumb_r,
                           fill_x + thumb_r, track_y + thumb_r,
                           fill=COLORS['white'], outline=COLORS['primary'], width=2)
        canvas.create_oval(fill_x - thumb_r + 3, track_y - thumb_r + 3,
                           fill_x + thumb_r - 3, track_y + thumb_r - 3,
                           fill=COLORS['primary'], outline='')

    def _slider_pos_to_value(self, x, idx):
        """Convert canvas x position to slider value (5-100)."""
        canvas = self.sliders[idx]['canvas']
        w = canvas.winfo_width()
        pad = 9
        pct = (x - pad) / max(1, w - 2 * pad)
        pct = max(0.0, min(1.0, pct))
        return int(round(5 + pct * 95))

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
        # Flush hardware immediately on release for snappy final state
        if not self._building:
            self._apply_all(include_hw=True)

    def _update_slider(self, idx, val):
        """Update slider value, label, and trigger brightness change."""
        val = max(5, min(100, int(val)))
        self.sliders[idx]['value'] = val
        if idx in self.val_labels:
            self.val_labels[idx].config(text=f'  {val}%  ')
        self.displays[idx]['brightness'] = val
        self._draw_slider(idx)
        if not self._building:
            self._schedule_apply()

    def _section_label(self, parent, text):
        tk.Label(parent, text=text.upper(), bg=COLORS['bg'], fg=COLORS['primary'],
                 font=FONT_SMALL).pack(anchor='w', padx=16, pady=(14, 6))

    def _show_settings(self):
        """Settings popup — XLab card layout, primary teal actions."""
        popup = tk.Toplevel(self.root)
        popup.title('XLight Settings')
        popup.configure(bg=COLORS['bg'])
        popup.geometry('360x420')
        popup.transient(self.root)
        popup.grab_set()
        try:
            ico = _icon_ico_path()
            if os.path.isfile(ico):
                popup.iconbitmap(ico)
        except Exception:
            pass

        # Popup header strip
        ph = tk.Frame(popup, bg=COLORS['bg'], height=48)
        ph.pack(fill=tk.X)
        ph.pack_propagate(False)
        tk.Label(ph, text='Settings', bg=COLORS['bg'], fg=COLORS['text'],
                 font=FONT_TITLE).pack(side=tk.LEFT, padx=16, pady=12)
        tk.Label(ph, text='XLab', bg=COLORS['bg'], fg=COLORS['primary'],
                 font=FONT_UI_BOLD).pack(side=tk.RIGHT, padx=16)
        tk.Frame(popup, bg=COLORS['primary'], height=2).pack(fill=tk.X)
        tk.Frame(popup, bg=COLORS['border'], height=1).pack(fill=tk.X)

        body = tk.Frame(popup, bg=COLORS['bg'])
        body.pack(fill=tk.BOTH, expand=True)

        # Profiles
        self._section_label(body, 'Profiles')
        for name in self.config.get('profiles', {}):
            btn = self._outline_btn(
                body, name,
                command=lambda n=name, p=popup: (self._apply_profile(n), p.destroy()),
            )
            btn.configure(anchor='w')
            btn.pack(fill=tk.X, padx=16, pady=2)

        self._primary_btn(
            body, '+  Save Current as Profile',
            command=lambda: (popup.destroy(), self._save_profile()),
        ).pack(fill=tk.X, padx=16, pady=(10, 4))

        tk.Frame(body, bg=COLORS['border'], height=1).pack(fill=tk.X, padx=16, pady=10)

        # Modes
        self._section_label(body, 'Brightness Mode')
        self.use_gamma = tk.BooleanVar(value=self.config.get('use_gamma', True))
        self.use_hw = tk.BooleanVar(value=self.config.get('use_hardware', True))

        cb_style = dict(
            bg=COLORS['bg'], fg=COLORS['text'], font=FONT_UI,
            selectcolor=COLORS['primary_50'], activebackground=COLORS['bg'],
            activeforeground=COLORS['primary'],
            highlightthickness=0, bd=0,
        )
        tk.Checkbutton(body, text='Software (Gamma Ramp)', variable=self.use_gamma,
                       command=self._on_mode, **cb_style).pack(anchor='w', padx=16, pady=2)
        hw_cb = tk.Checkbutton(body, text='Hardware (DDC/CI)', variable=self.use_hw,
                               command=self._on_mode, **cb_style)
        hw_cb.pack(anchor='w', padx=16, pady=2)
        if not self.hw_backend.available:
            self.use_hw.set(False)
            hw_cb.configure(state='disabled')

        tk.Frame(body, bg=COLORS['border'], height=1).pack(fill=tk.X, padx=16, pady=10)

        # Color temperature
        self._section_label(body, 'Color Temperature')
        temp_frame = tk.Frame(body, bg=COLORS['bg'])
        temp_frame.pack(fill=tk.X, padx=16, pady=(0, 12))

        self.temp_label = tk.Label(
            temp_frame, text=f"{self.config['temperature']}K",
            bg=COLORS['primary_50'], fg=COLORS['primary_600'],
            font=FONT_UI_BOLD, padx=8, pady=2,
        )
        self.temp_label.pack(side=tk.RIGHT)

        self.temp_var = tk.IntVar(value=self.config['temperature'])
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except Exception:
            pass
        style.configure(
            'XLab.Horizontal.TScale',
            background=COLORS['bg'],
            troughcolor=COLORS['slider_bg'],
            bordercolor=COLORS['border'],
            lightcolor=COLORS['primary'],
            darkcolor=COLORS['primary'],
            sliderthickness=16,
            sliderlength=16,
        )
        style.map('XLab.Horizontal.TScale',
                  background=[('active', COLORS['bg'])])
        temp_sl = ttk.Scale(
            temp_frame, from_=1000, to=10000,
            variable=self.temp_var, orient=tk.HORIZONTAL,
            style='XLab.Horizontal.TScale',
            command=self._on_temp,
        )
        temp_sl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

    # ── Event handlers ──

    def _on_temp(self, value):
        val = int(float(value))
        if hasattr(self, 'temp_label'):
            try:
                self.temp_label.config(text=f'{val}K')
            except Exception:
                pass
        self.config['temperature'] = val
        if not self._building:
            self._debounce()

    def _on_mode(self):
        self.config['use_gamma'] = self.use_gamma.get()
        self.config['use_hardware'] = self.use_hw.get()
        # Turning gamma off must restore identity ramp (color temp lingers otherwise)
        if not self.config['use_gamma']:
            for d in self.displays:
                try:
                    self.gamma_backend.reset_gamma(d['gamma_id'])
                except Exception:
                    pass
        self._apply_all()

    def _debounce(self):
        """Legacy alias — schedule a full apply."""
        self._schedule_apply()

    def _schedule_apply(self):
        """Apply brightness so the on-screen level matches the % label.

        DDC/CI is the source of truth when available (backlight % = UI %).
        Gamma is not stacked on top of DDC (that made 18% look like ~5%).
        """
        # Immediately clear gamma-dim on DDC displays so UI % is not double-dark
        self._apply_all(include_hw=False)
        if self._hw_timer is not None:
            try:
                self.root.after_cancel(self._hw_timer)
            except Exception:
                pass
        # Short debounce keeps DDC from flooding while still tracking the slider
        self._hw_timer = self.root.after(40, lambda: self._apply_all(include_hw=True))
        if self._save_timer is not None:
            try:
                self.root.after_cancel(self._save_timer)
            except Exception:
                pass
        self._save_timer = self.root.after(400, self._persist_config)

    def _persist_config(self):
        if self.displays:
            self.config['brightness'] = self.displays[0]['brightness']
        save_config(self.config)
        self._save_timer = None

    def _apply_all(self, include_hw=True):
        """Apply brightness so UI % matches real output.

        Priority per display:
          1. Hardware (DDC/CI) sets actual backlight to the labeled %
          2. Gamma only applies color temperature when DDC succeeded
          3. If no DDC, gamma alone dims (linear above 50%)
        Never stack gamma-dim + DDC at the same % (double-dark mismatch).
        """
        temperature = self.config['temperature']
        use_gamma = self.config.get('use_gamma', True)
        use_hw = self.config.get('use_hardware', True)

        for d in self.displays:
            br_pct = max(5, min(100, int(d.get('brightness', 100))))
            brightness = br_pct / 100.0
            can_hw = (use_hw and d.get('hw_supported')
                      and d.get('hw_index') is not None)
            hw_ok = False

            if include_hw and can_hw:
                try:
                    hw_ok = bool(self.hw_backend.set_brightness(br_pct, d['hw_index']))
                    # Verify DDC actually stuck (some "Generic" monitors report support
                    # but ignore writes — then % would not match real brightness).
                    if hw_ok:
                        actual = self.hw_backend.get_brightness(d['hw_index'])
                        if actual is not None and abs(int(actual) - br_pct) > 8:
                            hw_ok = False
                except Exception:
                    hw_ok = False

            if use_gamma:
                try:
                    if hw_ok:
                        # DDC owns brightness — gamma only for color temp
                        gamma_br = 1.0
                    elif can_hw and not include_hw:
                        # Waiting for DDC tick: keep gamma neutral to avoid double-dark
                        gamma_br = 1.0
                    else:
                        # No reliable DDC → software dim tracks the % label
                        gamma_br = brightness
                    self.gamma_backend.set_gamma(d['gamma_id'], gamma_br, temperature)
                except Exception:
                    pass

        if self.displays:
            self.config['brightness'] = self.displays[0]['brightness']

    def _apply_profile(self, name):
        profiles = self.config.get('profiles', {})
        if name not in profiles:
            return
        p = profiles[name]
        b = max(5, min(100, int(p.get('brightness', 100))))
        t_val = int(p.get('temperature', 6500))
        self.config['temperature'] = t_val
        if hasattr(self, 'temp_var'):
            try:
                self.temp_var.set(t_val)
            except Exception:
                pass
            if hasattr(self, 'temp_label'):
                try:
                    self.temp_label.config(text=f'{t_val}K')
                except Exception:
                    pass
        for i in range(len(self.displays)):
            self._update_slider(i, b)
        # Ensure apply even if sliders did not change (same brightness, new temp)
        if not self._building:
            self._debounce()

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
        self.config['brightness'] = 100
        self.config['temperature'] = 6500
        if hasattr(self, 'temp_var'):
            try:
                self.temp_var.set(6500)
            except Exception:
                pass
            if hasattr(self, 'temp_label'):
                try:
                    self.temp_label.config(text='6500K')
                except Exception:
                    pass
        for i in range(len(self.displays)):
            self._update_slider(i, 100)
        for d in self.displays:
            try:
                self.gamma_backend.reset_gamma(d['gamma_id'])
            except Exception:
                pass
            if (self.config.get('use_hardware', True)
                    and d.get('hw_supported') and d.get('hw_index') is not None):
                try:
                    self.hw_backend.set_brightness(100, d['hw_index'])
                except Exception:
                    pass
        self._persist_config()

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

    # ── Icons / System Tray (XLab Web logo) ──

    def _set_window_icon(self):
        """Apply XLab logo to the window title bar (.ico preferred on Windows)."""
        ico = _icon_ico_path()
        try:
            if os.path.isfile(ico):
                self.root.iconbitmap(ico)
                return
        except Exception:
            pass
        try:
            from PIL import ImageTk
            img = create_app_icon(32)
            self._icon_photo = ImageTk.PhotoImage(img)
            self.root.iconphoto(True, self._icon_photo)
        except Exception:
            pass

    def _setup_tray(self):
        """System tray icon using XLab Web logo."""
        self._tray_icon = None
        try:
            import pystray
            img = create_app_icon(64)
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
    print(f"\nCommands: b <0-100>, t <1000-10000>, r (reset), q (quit)")
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
                val = max(0, min(100, int(parts[1])))
                for d in displays:
                    gamma.set_gamma(d['id'], val/100.0, config.get('temperature', 6500))
                if hw.available:
                    hw.set_brightness(val)
                config['brightness'] = val
                save_config(config)
                print(f"Brightness: {val}%")
            except ValueError:
                print("Invalid. Use: b <0-100>")
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
