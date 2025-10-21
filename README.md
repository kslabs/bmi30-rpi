# BMI30 Streaming on Raspberry Pi

🚀 **Firmware, tools, and documentation for high-speed USB streaming on Raspberry Pi**

## Quick Start

```bash
git clone https://github.com/kslabs/bmi30-rpi
cd bmi30-rpi
chmod +x run_setup.sh run_test.sh
./run_setup.sh    # Install dependencies
./run_test.sh     # Flash firmware and test
```

## What's Inside

- **firmware/**: Compiled ELF for STM32H723VGT6
- **scripts/**: Python test tools (vendor_stream_read.py, etc.)
- **docs/**: Detailed setup and troubleshooting guides
- **run_setup.sh**: One-command dependency installation
- **run_test.sh**: Flash and test automation

## Hardware Required

- Raspberry Pi (3B+ or newer recommended)
- ST-Link v2 debugger
- STM32H723VGT6 microcontroller
- Jumper wires (GPIO 17, 27, GND)

## Expected Performance

- **Speed**: 1000-1250 KB/s (diagnostic mode)
- **Target**: ≥ 960 KB/s
- **USB**: Full Speed (12 Mbps)

## Documentation

See `START_HERE.md` for complete instructions.

---

**Status**: Ready for deployment ✅
