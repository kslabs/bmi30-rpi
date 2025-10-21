# Issue: IF#2 Vendor Bulk Interface Disappeared After Firmware Update

## Problem Description

After device developer flashed firmware update, the Vendor Bulk interface (IF#2) has **disappeared**.

### Current Device State
```
lsusb -d cafe:4001 -v
bNumInterfaces: 2  ❌ (was 3)

Interface 0: CDC Control (class=2)
  EP 0x82 (IN, Interrupt)

Interface 1: CDC Data (class=10)
  EP 0x01 (OUT, Bulk)
  EP 0x81 (IN, Bulk)

Interface 2: MISSING ❌
  (Previously: Vendor Bulk with EP 0x03 OUT, EP 0x83 IN)
```

### What We Expected
After firmware update, device should have:
- Interface 2: Vendor Bulk (class 255)
- EP 0x03 (OUT)
- EP 0x83 (IN)

### What Happened
IF#2 is no longer present. Device only shows CDC (CDC Control + CDC Data).

## Possible Causes
1. ❓ Firmware update incomplete (binary not fully written)
2. ❓ Device needs power cycle/reboot to apply changes
3. ❓ Firmware build issue (IF#2 not included in new binary)

## What to Check
1. Verify firmware binary includes Vendor Bulk descriptor
2. Check if device needs power cycle: unplug USB for 5 seconds, reconnect
3. Verify device memory contains correct firmware after flash
4. Check device logs for USB descriptor errors

## Test Command
```bash
# Current state (for reference)
lsusb -d cafe:4001 -v | grep "bNumInterfaces\|Interface\|0x03\|0x83"
```

## Additional Information

### Project Architecture
The project supports **both** modes:
1. **Vendor Bulk mode** (IF#2): Recommended, ~200 FPS
   - Used by: `BMI30.200.py` (GUI)
   - Module: `usb_vendor/usb_stream.py`
   - Spec: Interface 2 (class 255), EP 0x03 OUT, EP 0x83 IN
   - Status in docs: "READY FOR PRODUCTION"

2. **CDC mode** (IF#0 + IF#1): Legacy fallback, slower
   - Used by: `USB_receiver.py` (terminal-based)
   - Module: `USB_io.py`, `USB_proto.py`
   - Note: Can work but not recommended for oscilloscope display

### Current Situation
Device is now in **CDC mode only** (IF#0 + IF#1), missing IF#2 Vendor Bulk.

### Possible Causes
1. ❓ Firmware was not properly flashed (incomplete write)
2. ❓ Device has fallback logic (boots to CDC on error)
3. ❓ Firmware binary doesn't include Vendor Bulk descriptor
4. ❓ Configuration conflict or memory issue

## Action Needed
Device developer should:
1. ✅ Verify firmware source has IF#2 Vendor Bulk descriptor
2. ✅ Confirm firmware was fully written to device
3. ✅ Test: Device should show 3 interfaces on fresh connect
4. ✅ Check device logs for any errors during init
5. ✅ Re-compile and re-flash if needed

## Note
This is blocking oscilloscope display. The project depends on IF#2 Vendor Bulk for GUI `BMI30.200.py`.
CDC mode can work for legacy testing but won't give ~200 FPS visualization.
