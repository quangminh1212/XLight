#!/bin/bash
# XLight - Screen Brightness Controller
cd "$(dirname "$0")"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python 3 is not installed."
    echo "Install with: sudo apt install python3 python3-pip (Ubuntu/Debian)"
    echo "           or: brew install python3 (macOS)"
    exit 1
fi

# Install dependencies if needed
python3 -c "import screen_brightness_control, pystray, PIL" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "Installing dependencies..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to install dependencies."
        exit 1
    fi
fi

# Run XLight
python3 xlight.py "$@"
