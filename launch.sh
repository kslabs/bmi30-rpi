#!/bin/bash
# Quick Start Script for BMI30 USB Oscilloscope

set -e

echo "🚀 BMI30 USB Oscilloscope — Quick Start"
echo "=========================================="
echo ""

# Check if device is connected
echo "📡 Checking for BMI30 device (0xCAFE:0x4001)..."
if lsusb | grep -q "cafe:4001"; then
    echo "✅ Device found!"
else
    echo "⚠️  Device not found. Continuing anyway (will fail at runtime if not connected)..."
fi

# Check Python packages
echo ""
echo "📦 Checking Python packages..."
python3 << 'PY'
import sys
required = ['pyusb', 'pyqtgraph', 'numpy']
try:
    from PyQt5 import QtWidgets
    print("✅ PyQt5 found")
except:
    try:
        from PySide6 import QtWidgets
        print("✅ PySide6 found (fallback)")
    except:
        print("❌ Neither PyQt5 nor PySide6 found!")
        print("   Install: pip install PyQt5 pyqtgraph pyusb numpy")
        sys.exit(1)

for pkg in required:
    try:
        __import__(pkg)
        print(f"✅ {pkg} found")
    except ImportError:
        print(f"❌ {pkg} NOT found!")
        print(f"   Install: pip install {pkg}")
        sys.exit(1)
PY

if [ $? -ne 0 ]; then
    echo ""
    echo "Install missing packages:"
    echo "  pip install pyusb pyqtgraph PyQt5 numpy"
    exit 1
fi

# Check Python version
echo ""
echo "🐍 Checking Python version..."
PYVER=$(python3 --version | awk '{print $2}' | cut -d. -f1,2)
echo "   Python $PYVER"
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)"; then
    echo "✅ Python version OK (>= 3.7)"
else
    echo "❌ Python version too old (need >= 3.7)"
    exit 1
fi

# Check USB access
echo ""
echo "🔐 Checking USB access..."
if [ -e /dev/bus/usb ] && lsusb > /dev/null 2>&1; then
    echo "✅ USB access OK"
elif sudo -n lsusb > /dev/null 2>&1; then
    echo "⚠️  Will need to use 'sudo' for USB access"
    echo "   To avoid sudo, install udev rule:"
    echo "     sudo tee /etc/udev/rules.d/99-bmi30.rules << 'EOF'"
    echo "     SUBSYSTEMS==\"usb\", ATTRS{idVendor}==\"cafe\", ATTRS{idProduct}==\"4001\", MODE=\"0666\""
    echo "     EOF"
    echo "     sudo udevadm control --reload-rules"
    echo "     sudo udevadm trigger"
    NEED_SUDO=1
else
    echo "❌ Cannot access USB devices"
    exit 1
fi

# Launch GUI
echo ""
echo "🎬 Launching BMI30 Oscilloscope GUI..."
echo ""

cd "$(dirname "$0")"

if [ "$NEED_SUDO" = "1" ]; then
    sudo python3 BMI30.200.py "$@"
else
    python3 BMI30.200.py "$@"
fi
