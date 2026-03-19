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
    """Windows gamma control via Win32 GDI SetDeviceGammaRamp."""

    def __init__(self):
        import ctypes
        import ctypes.wintypes
        self.gdi32 = ctypes.windll.gdi32
        self.user32 = ctypes.windll.user32

    def _get_dc(self, display_name=None):
        if display_name:
            try:
                hdc = self.gdi32.CreateDCW(display_name, None, None, None)
                if hdc:
                    return hdc
            except Exception:
                pass
        return self.user32.GetDC(0)

    def _release_dc(self, hdc, display_name=None):
        if display_name:
            try:
                self.gdi32.DeleteDC(hdc)
            except Exception:
                self.user32.ReleaseDC(0, hdc)
        else:
            self.user32.ReleaseDC(0, hdc)

    def get_displays(self):
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
        import ctypes
        ramp = (ctypes.c_ushort * 256 * 3)()
        r_mult, g_mult, b_mult = _kelvin_to_rgb_multiplier(temperature)
        for i in range(256):
            val = int(i * 256 * brightness)
            ramp[0][i] = min(65535, int(val * r_mult))
            ramp[1][i] = min(65535, int(val * g_mult))
            ramp[2][i] = min(65535, int(val * b_mult))
        hdc = self._get_dc(display_id)
        try:
            self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        finally:
            self._release_dc(hdc, display_id)

    def reset_gamma(self, display_id):
        import ctypes
        ramp = (ctypes.c_ushort * 256 * 3)()
        for i in range(256):
            ramp[0][i] = ramp[1][i] = ramp[2][i] = i * 256
        hdc = self._get_dc(display_id)
        try:
            self.gdi32.SetDeviceGammaRamp(hdc, ctypes.byref(ramp))
        finally:
            self._release_dc(hdc, display_id)


class LinuxGammaBackend(GammaBackend):
    """Linux gamma control via xrandr."""
    def get_displays(self):
        import subprocess
        displays = []
        try:
            result = subprocess.run(['xrandr', '--listmonitors'],
                                    capture_output=True, text=True, timeout=5)
            for line in result.stdout.strip().split('\n')[1:]:
                parts = line.strip().split()
                if len(parts) >= 4:
                    name = parts[-1]
                    displays.append({'id': name, 'name': name, 'index': len(displays)})
        except Exception:
            pass
        if not displays:
            try:
                result = subprocess.run(['xrandr', '--query'],
                                        capture_output=True, text=True, timeout=5)
                for line in result.stdout.split('\n'):
                    if ' connected' in line:
                        name = line.split()[0]
                        displays.append({'id': name, 'name': name, 'index': len(displays)})
            except Exception:
                pass
        return displays if displays else [{'id': 'default', 'name': 'Default Display', 'index': 0}]

    def set_gamma(self, display_id, brightness, temperature):
        import subprocess
        r, g, b = _kelvin_to_rgb_multiplier(temperature)
        target = display_id if display_id and display_id != 'default' else None
        cmd = ['xrandr']
        if target:
            cmd += ['--output', target]
        cmd += ['--brightness', f'{brightness:.2f}',
                '--gamma', f'{1/max(0.1,brightness*r):.2f}:{1/max(0.1,brightness*g):.2f}:{1/max(0.1,brightness*b):.2f}']
        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
        except Exception:
            pass

    def reset_gamma(self, display_id):
        import subprocess
        cmd = ['xrandr']
        if display_id and display_id != 'default':
            cmd += ['--output', display_id]
        cmd += ['--brightness', '1.0', '--gamma', '1.0:1.0:1.0']
        try:
            subprocess.run(cmd, capture_output=True, timeout=5)
        except Exception:
            pass


class MacOSGammaBackend(GammaBackend):
    """macOS gamma control via CoreGraphics."""
    def __init__(self):
        import ctypes, ctypes.util
        self._cg = ctypes.CDLL(ctypes.util.find_library('CoreGraphics'))

    def get_displays(self):
        import ctypes
        ids = (ctypes.c_uint32 * 16)()
        count = ctypes.c_uint32(0)
        self._cg.CGGetActiveDisplayList(16, ids, ctypes.byref(count))
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
    'bg': '#1a1b26',
    'bg_card': '#24253a',
    'bg_hover': '#2f3050',
    'accent': '#7c6aef',
    'accent_hover': '#9585f5',
    'text': '#e0def4',
    'text_dim': '#6e6a86',
    'border': '#2a2b3d',
    'warm': '#ff9f43',
    'cool': '#74b9ff',
    'trough': '#16172b',
}


class XLightApp:
    """Compact brightness controller."""

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
        self.root.resizable(True, True)

        # Compact size
        n_displays = len(self.displays)
        win_h = 120 + n_displays * 52 + 52 + 52 + 44  # header+displays+temp+profiles+footer
        self.root.geometry(f'400x{win_h}')
        self.root.minsize(360, win_h)

        # Center
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - 200
        y = (self.root.winfo_screenheight() // 2) - (win_h // 2)
        self.root.geometry(f'+{x}+{y}')

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
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Slider.Horizontal.TScale',
                        background=COLORS['bg_card'],
                        troughcolor=COLORS['trough'],
                        sliderthickness=14, sliderlength=14)
        style.map('Slider.Horizontal.TScale',
                  background=[('active', COLORS['accent_hover'])])
        style.configure('Footer.TCheckbutton',
                        background=COLORS['bg'], foreground=COLORS['text_dim'],
                        font=('Segoe UI', 8))

        pad = tk.Frame(self.root, bg=COLORS['bg'])
        pad.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        # ── Header ──
        hdr = tk.Frame(pad, bg=COLORS['bg'])
        hdr.pack(fill=tk.X, pady=(0, 8))

        tk.Label(hdr, text='\u2600', bg=COLORS['bg'], fg=COLORS['accent'],
                 font=('Segoe UI', 15)).pack(side=tk.LEFT)
        tk.Label(hdr, text='XLight', bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Segoe UI', 13, 'bold')).pack(side=tk.LEFT, padx=(4, 0))

        # Reset button
        tk.Button(hdr, text='\u21BA', bg=COLORS['bg_card'], fg=COLORS['text_dim'],
                  font=('Segoe UI', 11), relief=tk.FLAT, padx=4, pady=0,
                  cursor='hand2', activebackground=COLORS['accent'],
                  activeforeground='white',
                  command=self._reset_all).pack(side=tk.RIGHT)

        # ── Per-display rows ──
        self.sliders = {}
        self.val_labels = {}

        for i, d in enumerate(self.displays):
            row = tk.Frame(pad, bg=COLORS['bg_card'])
            row.pack(fill=tk.X, pady=2, ipady=6)

            # Icon
            icon = '\U0001F5B5' if d.get('hw_supported') else '\U0001F4BB'
            tk.Label(row, text=icon, bg=COLORS['bg_card'], fg=COLORS['text_dim'],
                     font=('Segoe UI', 11)).pack(side=tk.LEFT, padx=(10, 4))

            # Name
            name = d['name'][:22] + '..' if len(d['name']) > 24 else d['name']
            tk.Label(row, text=name, bg=COLORS['bg_card'], fg=COLORS['text'],
                     font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 6))

            # Value
            vl = tk.Label(row, text=str(d['brightness']),
                          bg=COLORS['bg_card'], fg=COLORS['accent'],
                          font=('Segoe UI', 10, 'bold'), width=4, anchor='e')
            vl.pack(side=tk.RIGHT, padx=(4, 10))
            self.val_labels[i] = vl

            # Slider
            sl = ttk.Scale(row, from_=5, to=100, orient=tk.HORIZONTAL,
                           style='Slider.Horizontal.TScale',
                           command=lambda v, idx=i: self._on_slider(v, idx))
            sl.set(d['brightness'])
            sl.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(0, 4))
            self.sliders[i] = sl

        # ── Separator ──
        tk.Frame(pad, bg=COLORS['border'], height=1).pack(fill=tk.X, pady=6)

        # ── Temperature row ──
        temp_row = tk.Frame(pad, bg=COLORS['bg_card'])
        temp_row.pack(fill=tk.X, pady=2, ipady=6)

        self.temp_dot = tk.Canvas(temp_row, width=16, height=16,
                                  bg=COLORS['bg_card'], highlightthickness=0)
        self.temp_dot.pack(side=tk.LEFT, padx=(10, 4))
        self._draw_temp_dot(self.config['temperature'])

        tk.Label(temp_row, text=t('temperature', self.lang),
                 bg=COLORS['bg_card'], fg=COLORS['text'],
                 font=('Segoe UI', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 6))

        self.temp_label = tk.Label(temp_row, text=f"{self.config['temperature']}K",
                                   bg=COLORS['bg_card'], fg=COLORS['warm'],
                                   font=('Segoe UI', 10, 'bold'), width=6, anchor='e')
        self.temp_label.pack(side=tk.RIGHT, padx=(4, 10))

        self.temp_var = tk.IntVar(value=self.config['temperature'])
        temp_sl = ttk.Scale(temp_row, from_=1000, to=10000,
                            variable=self.temp_var, orient=tk.HORIZONTAL,
                            style='Slider.Horizontal.TScale',
                            command=self._on_temp)
        temp_sl.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(0, 4))

        # ── Separator ──
        tk.Frame(pad, bg=COLORS['border'], height=1).pack(fill=tk.X, pady=6)

        # ── Profiles row ──
        prof_row = tk.Frame(pad, bg=COLORS['bg'])
        prof_row.pack(fill=tk.X, pady=(0, 4))

        tk.Label(prof_row, text=t('profiles', self.lang),
                 bg=COLORS['bg'], fg=COLORS['text_dim'],
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(0, 6))

        self.profile_frame = tk.Frame(prof_row, bg=COLORS['bg'])
        self.profile_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._build_profile_pills()

        tk.Button(prof_row, text='+', bg=COLORS['bg_card'], fg=COLORS['accent'],
                  font=('Segoe UI', 9, 'bold'), relief=tk.FLAT, padx=5, pady=0,
                  cursor='hand2', activebackground=COLORS['accent'],
                  activeforeground='white',
                  command=self._save_profile).pack(side=tk.RIGHT, padx=(4, 0))

        # ── Footer ──
        foot = tk.Frame(pad, bg=COLORS['bg'])
        foot.pack(fill=tk.X, side=tk.BOTTOM, pady=(4, 0))

        self.use_gamma = tk.BooleanVar(value=self.config.get('use_gamma', True))
        self.use_hw = tk.BooleanVar(value=self.config.get('use_hardware', True))

        ttk.Checkbutton(foot, text='Gamma', variable=self.use_gamma,
                        style='Footer.TCheckbutton',
                        command=self._on_mode).pack(side=tk.LEFT)
        hw_cb = ttk.Checkbutton(foot, text='DDC/CI', variable=self.use_hw,
                                style='Footer.TCheckbutton',
                                command=self._on_mode)
        hw_cb.pack(side=tk.LEFT, padx=(8, 0))
        if not self.hw_backend.available:
            self.use_hw.set(False)
            hw_cb.configure(state='disabled')

        tk.Label(foot, text=f'{len(self.displays)} display(s) \u2022 {platform.system()}',
                 bg=COLORS['bg'], fg=COLORS['text_dim'],
                 font=('Segoe UI', 7)).pack(side=tk.RIGHT)

    def _draw_temp_dot(self, kelvin):
        r, g, b = _kelvin_to_rgb_multiplier(kelvin)
        color = f'#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}'
        self.temp_dot.delete('all')
        self.temp_dot.create_oval(1, 1, 15, 15, fill=color, outline=COLORS['border'])

    def _build_profile_pills(self):
        for w in self.profile_frame.winfo_children():
            w.destroy()
        for name in self.config.get('profiles', {}):
            tk.Button(self.profile_frame, text=name,
                      bg=COLORS['bg_card'], fg=COLORS['text'],
                      activebackground=COLORS['accent'], activeforeground='white',
                      font=('Segoe UI', 8), relief=tk.FLAT,
                      padx=8, pady=2, cursor='hand2',
                      command=lambda n=name: self._apply_profile(n)
                      ).pack(side=tk.LEFT, padx=2)

    # ── Event handlers ──

    def _on_slider(self, value, idx):
        val = int(float(value))
        self.val_labels[idx].config(text=str(val))
        self.displays[idx]['brightness'] = val
        if not self._building:
            self._debounce()

    def _on_temp(self, value):
        val = int(float(value))
        self.temp_label.config(text=f'{val}K')
        if val < 4000:
            self.temp_label.config(fg=COLORS['warm'])
        elif val > 7000:
            self.temp_label.config(fg=COLORS['cool'])
        else:
            self.temp_label.config(fg=COLORS['text'])
        self._draw_temp_dot(val)
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
            self.sliders[i].set(b)
            self.val_labels[i].config(text=str(b))
            self.displays[i]['brightness'] = b
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
            self._build_profile_pills()

    def _reset_all(self):
        for i in range(len(self.displays)):
            self.sliders[i].set(100)
            self.val_labels[i].config(text='100')
            self.displays[i]['brightness'] = 100
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
