# Issue Tracker for BMI30 Oscilloscope Project

**Последнее обновление**: 2025-10-21

---

## 🔴 CURRENT ISSUES (Blocking)

### Issue #1: IF#2 Vendor Bulk Not Available (Firmware Needs Flashing)

**Status**: 🔴 OPEN - Blocking oscilloscope GUI (Action Required)

**Severity**: Critical (blocks BMI30.200.py GUI)

**Update**: New firmware added (BMI30.stm32h7.elf at 2025-10-21 12:53)
- Firmware file is compiled and ready
- **Physical device still running old CDC-only version**
- Needs to be flashed to device via ST-Link programmer

**Description**:
After device developer flashed new firmware, the Vendor Bulk interface (IF#2) has disappeared.

**Current State**:
```
lsusb -d cafe:4001 -v shows:
bNumInterfaces: 2  ❌ (was 3)

Interface 0: CDC Control (class=2)
  EP 0x82 (IN, Interrupt)

Interface 1: CDC Data (class=10)
  EP 0x01 (OUT, Bulk)
  EP 0x81 (IN, Bulk)

Interface 2: MISSING ❌
  (Previously: Vendor Bulk with EP 0x03 OUT, EP 0x83 IN)
```

**Expected State**:
```
bNumInterfaces: 3  ✅

Interface 0: CDC Control (class=2)
Interface 1: CDC Data (class=10)  
Interface 2: Vendor Bulk (class=255) ← MISSING NOW
  EP 0x03 (OUT, Bulk)
  EP 0x83 (IN, Bulk)
```

**Root Cause Analysis**:
- Project architecture supports BOTH modes (Vendor Bulk recommended, CDC fallback)
- Vendor Bulk is required for oscilloscope GUI (`BMI30.200.py`)
- CDC mode works but slower, no high-frequency display
- Device now defaults to CDC only (Vendor Bulk descriptor missing)

**Possible Causes**:
1. Firmware not fully written to device (incomplete flash)
2. Firmware source code missing Vendor Bulk descriptor
3. Device has fallback logic (boots to CDC on error)
4. Compilation error in firmware build

**Test Command**:
```bash
lsusb -d cafe:4001 -v | grep "bNumInterfaces\|Interface"
```

**Action Required (Device Developer)**:
1. ✅ Verify firmware source has IF#2 Vendor Bulk descriptor
2. ✅ Check if firmware compilation includes all USB descriptors
3. ✅ Verify flash operation completed successfully
4. ✅ Check device logs for initialization errors
5. ✅ Re-compile and re-flash if needed
6. ✅ Confirm device shows 3 interfaces on fresh USB connect

**Workaround** (temporary):
- Use `USB_receiver.py --plot-fast` with CDC mode (slower, ~20 FPS instead of 200)
- Or wait for device developer to fix firmware

**Impact**:
- ❌ BMI30.200.py GUI cannot find IF#2 (blocks oscilloscope display)
- ❌ Cannot achieve ~200 FPS visualization
- ⚠️ Can fall back to CDC mode but with reduced performance

**Notes**:
- IF#2 briefly appeared in previous firmware iteration, then disappeared
- This suggests firmware update may have reverted or failed
- Both Vendor Bulk and CDC code paths exist in project (confirmed in `usb_vendor/usb_stream.py` and `USB_receiver.py`)

### Action Items (For Flashing New Firmware)

**New firmware ready** (as of 2025-10-21 12:53):
- Location: `firmware/BMI30.stm32h7.elf`
- Size: 2,460,668 bytes
- Status: Compiled and ready
- Documentation: See `DEVICE_STATUS.md` for flashing instructions

**Hardware Required**:
- ST-Link v2 programmer (device developer's responsibility)
- GPIO pins on Raspberry Pi (Pin 11, 13, 9/25 for SWDIO/SWDCLK/GND)
- USB cable for device

**Flashing Steps** (device developer):
1. Connect ST-Link to RPi GPIO
2. Run OpenOCD commands or `flash_firmware.sh` script
3. Device will reboot in Vendor Bulk mode (IF#2 will appear)
4. Verify: `lsusb -d cafe:4001 -v` shows bNumInterfaces=3

**Next Steps After Flashing**:
1. Device reconnects → IF#2 appears with EP 0x03/0x83
2. Host runs: `python3 BMI30.200.py`
3. GUI displays oscilloscope at ~200 FPS

---

## 🟡 RESOLVED ISSUES (For Reference)

### Issue #0: EP0 Commands Failing with I/O Error (RESOLVED)

**Status**: ✅ RESOLVED (IF#2 was briefly working)

**What Happened**:
- When IF#2 appeared, EP0 bulk OUT commands failed with errno 5
- All command types failed (START_STREAM, STOP_STREAM, SET_PROFILE, SET_FULL_MODE)
- STAT v1 reads worked fine (proving EP0 partially functional)

**Resolution**:
- This was firmware issue on device side
- When IF#2 disappeared, this issue became moot
- Current priority: Get IF#2 back (Issue #1)

---

## 📋 TRACKING CHECKLIST

### For Current Issue #1:
- [ ] ✅ Developer adds compiled firmware to repo (DONE: 2025-10-21 12:53)
- [ ] Developer connects ST-Link to RPi GPIO
- [ ] Developer flashes firmware via OpenOCD
- [ ] Device reboots and shows IF#2 in lsusb
- [ ] Host runs BMI30.200.py
- [ ] GUI connects to IF#2 (Vendor Bulk)
- [ ] Data stream flows (~200 FPS)
- [ ] Oscilloscope displays ADC0 and ADC1 synchronized
- [ ] Issue marked RESOLVED

### Post-Resolution Validation:
- [ ] Test profile=1 (200 Hz, 1360 samples/sec)
- [ ] Test profile=2 (300 Hz, 912 samples/sec)
- [ ] Verify A/B pair synchronization
- [ ] Verify STAT v1 parsing
- [ ] Verify GUI responsiveness (~200 FPS)

---

## 🔗 Project Architecture Reference

### Dual-Mode Support

**Mode 1: Vendor Bulk (IF#2)** ⭐ Recommended
- GUI: `BMI30.200.py` (PyQtGraph oscilloscope)
- Transport: `usb_vendor/usb_stream.py`
- Performance: ~200 FPS (profile=1) or ~300 FPS (profile=2)
- Status: READY FOR PRODUCTION (per GitHub README)

**Mode 2: CDC (IF#0 + IF#1)** (Legacy fallback)
- GUI: `USB_receiver.py` (terminal-based or `--plot-fast`)
- Transport: `USB_io.py`, `USB_proto.py`
- Performance: ~20 FPS (slower)
- Usage: For debugging/testing when IF#2 unavailable

### Key Files
| File | Purpose | Lines |
|------|---------|-------|
| `BMI30.200.py` | Main oscilloscope GUI | 1113 |
| `usb_vendor/usb_stream.py` | USB transport (Vendor Bulk) | ~850 |
| `USB_receiver.py` | USB transport (CDC) | 870 |
| `QUICKSTART.md` | User quick-start guide | updated |
| `LAUNCH.md` | Full launch documentation | GitHub |

---

## 📝 Communication Protocol

When reporting findings:
1. **Check this file FIRST** before creating new issue
2. **Consolidate** - don't create duplicate issue files
3. **Update Status** - mark resolved when fixed
4. **Link References** - reference GitHub docs/code locations
5. **Provide Test Commands** - make verification easy

---

**End of Issues Tracker**
