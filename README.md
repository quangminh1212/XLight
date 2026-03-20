<p align="center">
  <h1 align="center">☀️ XLight</h1>
  <p align="center"><strong>Cross-Platform Screen Brightness & Color Temperature Controller</strong></p>
  <p align="center">
    A lightweight, open-source application to control screen brightness and color temperature on <b>any monitor</b> across <b>Windows, Linux, and macOS</b>.
  </p>
</p>

<p align="center">
  <a href="https://github.com/quangminh1212/XLight/blob/main/LICENSE"><img src="https://img.shields.io/github/license/quangminh1212/XLight?style=flat-square&color=blue" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.8+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://www.npmjs.com/package/xlight"><img src="https://img.shields.io/npm/v/xlight?style=flat-square&logo=npm&color=CB3837" alt="npm"></a>
  <a href="https://pypi.org/project/xlight/"><img src="https://img.shields.io/pypi/v/xlight?style=flat-square&logo=pypi&logoColor=white&color=3775A9" alt="PyPI"></a>
  <a href="https://github.com/quangminh1212/XLight"><img src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey?style=flat-square" alt="Platform"></a>
  <a href="https://github.com/quangminh1212/XLight/stargazers"><img src="https://img.shields.io/github/stars/quangminh1212/XLight?style=flat-square&color=yellow" alt="Stars"></a>
  <a href="https://github.com/quangminh1212/XLight/network/members"><img src="https://img.shields.io/github/forks/quangminh1212/XLight?style=flat-square&color=green" alt="Forks"></a>
  <a href="https://github.com/quangminh1212/XLight/issues"><img src="https://img.shields.io/github/issues/quangminh1212/XLight?style=flat-square&color=red" alt="Issues"></a>
  <a href="https://github.com/quangminh1212/XLight/pulls"><img src="https://img.shields.io/github/issues-pr/quangminh1212/XLight?style=flat-square&color=orange" alt="Pull Requests"></a>
  <a href="https://github.com/quangminh1212/XLight"><img src="https://img.shields.io/github/repo-size/quangminh1212/XLight?style=flat-square" alt="Repo Size"></a>
  <a href="https://github.com/quangminh1212/XLight"><img src="https://img.shields.io/github/last-commit/quangminh1212/XLight?style=flat-square&color=purple" alt="Last Commit"></a>
</p>

---

## ✨ Features

| Feature | Description |
|---|---|
| 🔆 **Dual Engine** | Software (Gamma Ramp) + Hardware (DDC/CI) brightness control — choose which engine to use or combine both |
| 🖥️ **Universal Compatibility** | Works with **ALL** monitor types — internal displays, external monitors, VGA, HDMI, DisplayPort, USB-C, Thunderbolt |
| 🖥️🖥️ **Multi-Monitor** | Independent brightness control per display with individual sliders — mixed monitor setups fully supported |
| 🌡️ **Color Temperature** | Adjustable from 1000K (warm candlelight) to 10000K (cool daylight) — smooth real-time transition |
| 📋 **Profiles** | Built-in presets (Day, Evening, Night, Reading) + create unlimited custom profiles with one click |
| 🔽 **System Tray** | Minimize to system tray for background running, quick access via tray icon with right-click menu |
| 🌍 **Cross-Platform** | Windows, Linux (X11 + Wayland), macOS — single Python codebase, consistent behavior everywhere |
| 💻 **CLI Mode** | Full-featured command-line interface — perfect for headless servers, SSH sessions, or scripting |
| 🎨 **Compact UI** | Twinkle Tray-inspired minimal interface with custom canvas sliders, clean typography, and smooth interactions |
| 🌐 **i18n** | Multi-language support (English, Vietnamese) — easily extensible |
| ⚙️ **Auto-save** | Settings persist automatically across restarts — stored in platform-appropriate config directory |
| 🔄 **Smart Fallback** | Automatically falls back to CLI mode if no display server is available |

---

## 🚀 How It Works

XLight uses a **dual-engine architecture** to ensure maximum compatibility with any setup:

### Engine 1: Gamma Ramp (Software)
Adjusts display gamma tables via native OS APIs — works on **ANY** monitor regardless of cable type or hardware support.

| Platform | API | Method |
|---|---|---|
| **Windows** | `SetDeviceGammaRamp` (GDI32) | Per-display DC via `CreateDCW` with `EnumDisplayDevicesW` |
| **Linux X11** | `xrandr` | Per-output `--brightness` and `--gamma` control |
| **Linux Wayland** | `wlr-randr` / `brightnessctl` / sysfs | Automatic detection with fallback chain |
| **macOS** | `CGSetDisplayTransferByTable` (CoreGraphics) | Per-display ID with `CGGetActiveDisplayList` |

> ✅ **Gamma Ramp works on ANY monitor** — no hardware support required. This is the universal fallback.

### Engine 2: DDC/CI (Hardware)
Direct Digital Control via monitor's I²C bus — adjusts the monitor's **actual backlight** for a true brightness change.

- Uses [`screen_brightness_control`](https://github.com/Crozzers/screen_brightness_control) library
- ✅ Adjusts the monitor's **real hardware backlight** — visible even in dark rooms
- ⚠️ Requires DDC/CI-capable monitor (most modern displays support this over HDMI/DisplayPort)

### Color Temperature Engine
Based on **Tanner Helland's algorithm** (same math used by f.lux, Redshift, and Night Light):
- Maps Kelvin values (1000K–10000K) to RGB multipliers
- Applied via gamma ramp for instant, smooth color transitions
- No additional drivers or hardware required

---

## 📦 Installation

### Method 1: pip (Recommended)

```bash
pip install xlight
```

After installation, run:
```bash
xlight
```

### Method 2: npm (Node.js wrapper)

```bash
npm install -g xlight
```

This installs the `xlight` command globally. It requires Python 3.8+ to be installed on your system.

```bash
xlight
```

### Method 3: From Source (Development)

```bash
# 1. Clone the repository
git clone https://github.com/quangminh1212/XLight.git
cd XLight

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Run
python xlight.py
```

### Quick Launchers

**Windows** — double-click or run in terminal:
```batch
run.bat
```

**Linux / macOS** — make executable and run:
```bash
chmod +x run.sh
./run.sh
```

> 💡 The launcher scripts automatically check for Python, install missing dependencies, and start XLight.

---

## 🔧 Platform-Specific Setup

### Windows
- ✅ **No extra setup needed** — works out of the box
- Python 3.8+ required ([download](https://python.org))
- `tkinter` is included with the standard Python installer

### Linux (Ubuntu/Debian)
```bash
# Required: tkinter for GUI
sudo apt install python3-tk

# Optional: DDC/CI hardware brightness control
sudo apt install ddcutil
sudo usermod -aG i2c $USER
# Log out and back in for group changes to take effect

# Optional: Wayland compositors (Sway, Hyprland, etc.)
sudo apt install wlr-randr

# Optional: Laptop backlight control
sudo apt install brightnessctl
```

### Linux (Fedora)
```bash
sudo dnf install python3-tkinter
sudo dnf install ddcutil    # Optional: DDC/CI
```

### Linux (Arch)
```bash
sudo pacman -S tk
sudo pacman -S ddcutil      # Optional: DDC/CI
```

### macOS
- ✅ `tkinter` is included with Python from [python.org](https://python.org) or Homebrew
- CoreGraphics is available natively — no extra setup
- ⚠️ DDC/CI has limited support on macOS — use Gamma mode for best results

```bash
# If using Homebrew Python
brew install python-tk@3.12
```

---

## 📖 Usage

### GUI Mode (Default)

```bash
python xlight.py
# or after pip/npm install:
xlight
```

The compact Twinkle Tray-styled window provides:

| Element | Description |
|---|---|
| **Per-display sliders** | Each connected monitor has its own brightness slider (5%–100%) |
| **Percentage labels** | Real-time percentage display next to each slider |
| **Settings gear (⚙)** | Opens popup with profiles, engine toggles, and color temperature |
| **Reset button (↺)** | Restores all displays to 100% brightness and 6500K |
| **Profile pills** | One-click apply for Day, Evening, Night, Reading, or custom profiles |
| **Engine toggles** | Enable/disable Gamma (software) and DDC/CI (hardware) engines independently |
| **Color temperature slider** | Adjust from 1000K (warm) to 10000K (cool) with live preview |
| **System tray icon** | Close window to minimize to tray — right-click for Show/Reset/Quit |

### CLI Mode

```bash
python xlight.py --cli
# or
xlight --cli
```

Interactive commands:

| Command | Action | Example |
|---|---|---|
| `b <5-100>` | Set brightness percentage | `b 70` → set to 70% |
| `t <1000-10000>` | Set color temperature (Kelvin) | `t 3200` → warm night mode |
| `r` | Reset to defaults (100%, 6500K) | |
| `q` | Quit and restore original settings | |

> 💡 CLI mode automatically activates when no display server (X11/Wayland) is available — perfect for SSH sessions.

---

## ⚙️ Configuration

Settings are automatically saved and persist across restarts. Stored in platform-appropriate locations:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\XLight\settings.json` |
| macOS | `~/Library/Application Support/XLight/settings.json` |
| Linux | `~/.config/XLight/settings.json` |

### Settings Schema

```json
{
  "brightness": 100,
  "temperature": 6500,
  "use_hardware": true,
  "use_gamma": true,
  "profiles": {
    "Day":     { "brightness": 100, "temperature": 6500 },
    "Evening": { "brightness": 70,  "temperature": 4500 },
    "Night":   { "brightness": 40,  "temperature": 3200 },
    "Reading": { "brightness": 80,  "temperature": 5500 }
  },
  "language": "en"
}
```

| Field | Type | Default | Description |
|---|---|---|---|
| `brightness` | int | `100` | Global brightness percentage (5–100) |
| `temperature` | int | `6500` | Color temperature in Kelvin (1000–10000) |
| `use_hardware` | bool | `true` | Enable DDC/CI hardware brightness control |
| `use_gamma` | bool | `true` | Enable software gamma ramp brightness |
| `profiles` | object | *(4 presets)* | Named brightness + temperature presets |
| `language` | string | `"en"` | UI language code (`"en"`, `"vi"`) |

---

## 📁 Project Structure

```
XLight/
├── xlight.py          # Main application — all-in-one Python script
├── pyproject.toml     # Python package configuration (pip/PyPI)
├── requirements.txt   # Python dependencies
├── run.bat            # Windows one-click launcher
├── run.sh             # Linux/macOS one-click launcher
├── test_run.py        # Automated test suite
├── npm/               # npm package wrapper (Node.js)
│   ├── package.json   # npm configuration
│   ├── bin/           # CLI entry point (xlight.js)
│   └── python/        # Bundled Python source
├── scripts/           # Build & packaging scripts
├── LICENSE            # MIT License
└── README.md          # This file
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────┐
│                  XLightApp                   │
│  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │  GUI     │  │ Profiles │  │  Config   │ │
│  │ (tkinter)│  │ Manager  │  │ (JSON)    │ │
│  └────┬─────┘  └──────────┘  └───────────┘ │
│       │                                      │
│  ┌────▼──────────────────────────────────┐  │
│  │         Brightness Controller          │  │
│  │  ┌────────────┐  ┌─────────────────┐  │  │
│  │  │ GammaBackend│  │ HardwareBackend │  │  │
│  │  │ (Software) │  │   (DDC/CI)      │  │  │
│  │  └─────┬──────┘  └───────┬─────────┘  │  │
│  └────────┼──────────────────┼────────────┘  │
│           │                  │               │
├───────────┼──────────────────┼───────────────┤
│      OS Display API     Monitor I²C Bus      │
│  Win: GDI32            screen_brightness_ctrl │
│  Linux: xrandr/wlr/                           │
│         brightnessctl/sysfs                    │
│  macOS: CoreGraphics                          │
└─────────────────────────────────────────────┘
```

---

## 📊 Platform Support Matrix

| Feature | Windows | Linux (X11) | Linux (Wayland) | macOS |
|---|:---:|:---:|:---:|:---:|
| Software Brightness (Gamma) | ✅ | ✅ xrandr | ✅ wlr-randr/brightnessctl | ✅ CoreGraphics |
| Hardware Brightness (DDC/CI) | ✅ | ✅ | ✅ | ⚠️ |
| Color Temperature | ✅ | ✅ | ✅ | ✅ |
| Multi-Monitor (mixed types) | ✅ | ✅ | ✅ | ✅ |
| Laptop Built-in Display | ✅ WMI | ✅ sysfs/brightnessctl | ✅ sysfs/brightnessctl | ✅ |
| System Tray | ✅ | ✅ | ✅ | ✅ |
| CLI Mode | ✅ | ✅ | ✅ | ✅ |

> ⚠️ macOS DDC/CI requires additional setup and may not work with all monitors.

---

## 🔌 Monitor Cable Type Compatibility

Gamma Ramp (software) works with **ALL** cable types. DDC/CI availability depends on the monitor:

| Cable Type | Gamma (Software) | DDC/CI (Hardware) | Notes |
|---|:---:|:---:|---|
| HDMI | ✅ | ✅ Usually | Most monitors support DDC over HDMI |
| DisplayPort | ✅ | ✅ Usually | Best DDC/CI support |
| USB-C / Thunderbolt | ✅ | ✅ Varies | Depends on adapter/dock |
| DVI-D | ✅ | ✅ Usually | Digital DVI supports DDC |
| DVI-A / VGA | ✅ | ❌ Rare | Analog — gamma ramp only |
| Laptop Built-in | ✅ | ✅ WMI/sysfs | Uses OS backlight API, not DDC |

---

## 🌡️ Color Temperature Reference

| Kelvin | Equivalent | Use Case |
|:---:|---|---|
| 1000K | 🕯️ Candlelight | Extreme night mode |
| 2700K | 💡 Incandescent bulb | Relaxed evening |
| 3200K | Warm white (halogen) | Night reading |
| 4500K | Fluorescent | Late afternoon |
| 5500K | ☀️ Direct sunlight | Daytime work |
| 6500K | ☁️ Overcast sky (sRGB) | Default/neutral |
| 7500K | Cloudy sky | Slightly cool |
| 10000K | 🔵 Blue sky | Maximum cool |

---

## 🔍 Troubleshooting

<details>
<summary><strong>Brightness doesn't change</strong></summary>

- Enable **Gamma** mode (software) in Settings — this works on all monitors regardless of cable type
- If using DDC/CI, check your monitor's OSD → DDC/CI setting is enabled
- On Linux X11, ensure `xrandr` is available: `which xrandr`
- On Linux Wayland, install `wlr-randr` or `brightnessctl`
</details>

<details>
<summary><strong>Multi-monitor: Only one monitor changes</strong></summary>

- XLight creates per-display device contexts (Windows: `CreateDCW`, Linux: `--output`)
- If one monitor doesn't respond, it may not support gamma ramp (very rare)
- DDC/CI for specific monitors may require compatible cable (HDMI/DP preferred over VGA)
</details>

<details>
<summary><strong>VGA/Analog monitor not responding to DDC</strong></summary>

- VGA cables don't support DDC/CI — use **Gamma mode** instead (always works)
- Enable the Software (Gamma Ramp) checkbox in Settings
</details>

<details>
<summary><strong>Monitor not detected</strong></summary>

- Check cable connection (try HDMI/DP instead of VGA for best compatibility)
- On Linux, install `ddcutil` and add user to `i2c` group: `sudo usermod -aG i2c $USER`
- Try restarting the application
</details>

<details>
<summary><strong>Gamma resets after reboot</strong></summary>

- This is expected — gamma ramp changes are temporary (same as f.lux, Redshift)
- Add XLight to your startup programs to reapply settings automatically
</details>

<details>
<summary><strong>Linux Wayland: No gamma control</strong></summary>

```bash
# For wlroots-based compositors (Sway, Hyprland)
sudo apt install wlr-randr
# OR for laptop backlight
sudo apt install brightnessctl
```
</details>

<details>
<summary><strong>Linux: python3-tk not found</strong></summary>

```bash
sudo apt install python3-tk          # Debian/Ubuntu
sudo dnf install python3-tkinter      # Fedora
sudo pacman -S tk                     # Arch
```
</details>

---

## 🤝 Contributing

Contributions are welcome! Here's how to get started:

1. **Fork** the repository
2. **Clone** your fork: `git clone https://github.com/your-username/XLight.git`
3. **Create a branch**: `git checkout -b feature/my-feature`
4. **Make changes** and test thoroughly
5. **Commit**: `git commit -m "feat: add my feature"`
6. **Push**: `git push origin feature/my-feature`
7. **Open a Pull Request**

Please follow [Conventional Commits](https://www.conventionalcommits.org/) for commit messages.

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

Copyright © 2026 XLight Team

---

## 🙏 Credits

- **Color Temperature Algorithm**: [Tanner Helland](http://www.tannerhelland.com/4435/convert-temperature-rgb-algorithm-code/)
- **Hardware Brightness**: [screen_brightness_control](https://github.com/Crozzers/screen_brightness_control) by Crozzers
- **System Tray**: [pystray](https://github.com/moses-palmer/pystray) by Moses Palmér
- **Icon Rendering**: [Pillow](https://python-pillow.org/)
- **Inspiration**: [Twinkle Tray](https://twinkletray.com/), [f.lux](https://justgetflux.com/), [Redshift](http://jonls.dk/redshift/)

---

<p align="center">
  Made with ❤️ by the <a href="https://github.com/quangminh1212/XLight">XLight Team</a>
</p>
