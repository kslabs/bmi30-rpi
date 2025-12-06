# Issue: Device Showing CDC Mode Instead of Vendor Bulk

## Problem Summary
Device is detected as 0xCAFE:0x4001 but reports CDC configuration (IF#0, IF#1) instead of expected Vendor Bulk (IF#2).

## Current USB Configuration
```
Interface 0: CDC Control (class 2)
  └─ EP 0x82 (Interrupt IN)

Interface 1: CDC Data (class 10)
  ├─ EP 0x01 (Bulk OUT)
  └─ EP 0x81 (Bulk IN)
```

## Expected USB Configuration
```
Interface 2: Vendor Bulk (class 255)
  ├─ EP 0x03 (Bulk OUT)
  └─ EP 0x83 (Bulk IN)
```

## Steps to Reproduce
1. Connect BMI30 device (0xCAFE:0x4001) via USB
2. Run: `lsusb -d cafe:4001 -v`
3. Observe: Only IF#0 and IF#1 present, IF#2 missing

## Expected Behavior
- Device should enumerate with Interface 2 (Vendor Bulk)
- Endpoints 0x03 and 0x83 should be accessible
- GUI (BMI30.200.py) should be able to open device and receive data

## System Information
- OS: Linux (Raspberry Pi)
- Python: 3.11
- PyUSB: Installed ✓
- Device State: Connected and visible to lsusb

## Diagnostic Output
```
lsusb -d cafe:4001 -v output:
Bus 001 Device 002: ID cafe:4001 WeAct BMI30 Streamer
Configuration: 1
Interfaces: 2
  Interface 0: CDC Control
  Interface 1: CDC Data
```

## Action Required
- [ ] Check firmware configuration
- [ ] Flash device with correct Vendor Bulk firmware
- [ ] Verify IF#2 with EP 0x03/0x83 appears
- [ ] Notify when ready for testing

## Notes
GUI code and USB transport are ready. Waiting for device to report correct Vendor Bulk interface.
