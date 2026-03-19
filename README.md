# XLight

**Cross-Platform Screen Brightness & Color Temperature Controller**

A lightweight, open-source application to control screen brightness and color temperature on **any monitor** across **Windows, Linux, and macOS**.

---

## Features

| Feature | Description |
|---|---|
| **Dual Engine** | Software (Gamma Ramp) + Hardware (DDC/CI) brightness control |
| **Universal Compatibility** | Works with ALL monitor types — internal, external, VGA, HDMI, DisplayPort |
| **Multi-Monitor** | Independent brightness control per display |
| **Color Temperature** | Adjustable from 1000K (warm/night) to 10000K (cool/daylight) |
| **Profiles** | Built-in presets (Day, Evening, Night, Reading) + custom profiles |
| **System Tray** | Minimize to tray, quick access via icon |
| **Cross-Platform** | Windows, Linux, macOS — same codebase |
| **CLI Mode** | Headless/terminal fallback for servers |
| **Compact UI** | Twinkle Tray-inspired minimal interface |

---

## How It Works

XLight uses a **dual-engine architecture** to ensure maximum compatibility:

### Engine 1: Gamma Ramp (Software)
- Adjusts display gamma tables via OS APIs
- **Windows**: `SetDeviceGammaRamp` (GDI32)
- **Linux**: `xrandr --brightness --gamma`
- **macOS**: `CGSetDisplayTransferByTable` (CoreGraphics)
- ✅ Works on **ANY** monitor — no hardware support required

### Engine 2: DDC/CI (Hardware)
- Direct Digital Control via monitor's I²C bus
- Uses [`screen_brightness_control`](https://github.com/Crozzers/screen_brightness_control) library
- ✅ Adjusts the monitor's **actual backlight** — true brightness change
- ⚠️ Requires DDC/CI-capable monitor (most modern displays)

### Color Temperature
- Based on **Tanner Helland's algorithm** (same as f.lux, Redshift)
- Maps Kelvin values to RGB multipliers applied via gamma ramp
- Smooth transition from warm (1000K) to cool (10000K)

---

## Requirements

- **Python** 3.8+
- **tkinter** (included with Python on Windows/macOS, install `python3-tk` on Linux)

### Dependencies

```
screen_brightness_control >= 0.20.0   # Hardware brightness (DDC/CI)
pystray >= 0.19.0                     # System tray icon
Pillow >= 10.0.0                      # Tray icon rendering
```

---

## Installation

### Quick Start (All Platforms)

```bash
# Clone
git clone https://github.com/your-repo/XLight.git
cd XLight

# Install dependencies
pip install -r requirements.txt

# Run
python xlight.py
```

### Windows
```batch
run.bat
```

### Linux / macOS
```bash
chmod +x run.sh
./run.sh
```

### Linux Extra Dependencies

```bash
# Ubuntu/Debian
sudo apt install python3-tk

# For DDC/CI hardware control
sudo apt install ddcutil
sudo usermod -aG i2c $USER
```

---

## Usage

### GUI Mode (Default)

```bash
python xlight.py
```

The compact window shows:
- **Per-display brightness sliders** — each monitor has its own row
- **Color temperature slider** — with live preview dot
- **Profile pills** — click to apply preset (Day, Evening, Night, Reading)
- **Mode toggles** — enable/disable Gamma and DDC/CI engines
- **Reset button** (↺) — restore defaults

### CLI Mode

```bash
python xlight.py --cli
```

Commands:
| Command | Action |
|---|---|
| `b <5-100>` | Set brightness percentage |
| `t <1000-10000>` | Set color temperature (Kelvin) |
| `r` | Reset to defaults |
| `q` | Quit |

---

## Configuration

Settings are stored in a platform-appropriate location:

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

---

## Project Structure

```
XLight/
├── xlight.py          # Main application (all-in-one)
├── requirements.txt   # Python dependencies
├── run.bat            # Windows launcher
├── run.sh             # Linux/macOS launcher
├── test_run.py        # Automated test suite
├── .gitignore         # Git ignore rules
└── README.md          # This file
```

---

## Architecture

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
│  Linux: xrandr                                │
│  macOS: CoreGraphics                          │
└─────────────────────────────────────────────┘
```

---

## Platform Support Matrix

| Feature | Windows | Linux | macOS |
|---|:---:|:---:|:---:|
| Software Brightness (Gamma) | ✅ | ✅ | ✅ |
| Hardware Brightness (DDC/CI) | ✅ | ✅ | ⚠️ |
| Color Temperature | ✅ | ✅ | ✅ |
| Multi-Monitor | ✅ | ✅ | ✅ |
| System Tray | ✅ | ✅ | ✅ |
| CLI Mode | ✅ | ✅ | ✅ |

> ⚠️ macOS DDC/CI requires additional setup and may not work with all monitors.

---

## Color Temperature Reference

| Kelvin | Equivalent | Use Case |
|:---:|---|---|
| 1000K | Candlelight | Extreme night mode |
| 2700K | Incandescent bulb | Relaxed evening |
| 3200K | Warm white (halogen) | Night reading |
| 4500K | Fluorescent | Late afternoon |
| 5500K | Direct sunlight | Daytime work |
| 6500K | Overcast sky (sRGB) | Default/neutral |
| 7500K | Cloudy sky | Slightly cool |
| 10000K | Blue sky | Maximum cool |

---

## Troubleshooting

### Brightness doesn't change
- Enable **Gamma** mode (software) — works on all monitors
- If using DDC/CI, ensure your monitor supports it (check monitor OSD menu)
- On Linux, ensure `xrandr` is available

### Monitor not detected
- Check cable connection (DDC/CI requires compatible cable)
- On Linux, install `ddcutil` and add user to `i2c` group
- Try restarting the application

### Gamma resets after reboot
- This is expected — gamma ramp changes are temporary
- Run XLight at startup to reapply settings

### Linux: `python3-tk` not found
```bash
sudo apt install python3-tk  # Debian/Ubuntu
sudo dnf install python3-tkinter  # Fedora
sudo pacman -S tk  # Arch
```

---

## License

MIT License — see [LICENSE](LICENSE) for details.

---

## Credits

- **Color Temperature Algorithm**: [Tanner Helland](http://www.tannerhelland.com/4435/convert-temperature-rgb-algorithm-code/)
- **Hardware Brightness**: [screen_brightness_control](https://github.com/Crozzers/screen_brightness_control)
- **System Tray**: [pystray](https://github.com/moses-palmer/pystray)
- **Inspiration**: [Twinkle Tray](https://twinkletray.com/), [f.lux](https://justgetflux.com/)
