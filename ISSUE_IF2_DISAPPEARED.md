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

## Action Needed
Device developer should:
1. ✅ Verify firmware binary has Vendor Bulk descriptor
2. ✅ Test power cycle
3. ✅ Re-flash if needed
4. ✅ Confirm IF#2 appears on fresh connect

## Note
This is blocking data stream. Cannot proceed without IF#2 with correct endpoints.
