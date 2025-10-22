# Issue Tracker for BMI30 Oscilloscope Project

**Последнее обновление**: 2025-10-21 ~19:00

---

## 🔴 CURRENT ISSUES (Blocking)

### Issue #1: EP0 IN (GET_STATUS) Timeout + Device Firmware Regression

**Status**: 🔴 OPEN - Blocking oscilloscope GUI

**Severity**: Critical (blocks BMI30.200.py GUI)

**Latest Status** (2025-10-21 ~19:00):
- ✅ IF#2 (Vendor Bulk) **STILL PRESENT** in lsusb
- ✅ Interfaces: 3 (IF#0 CDC Control, IF#1 CDC Data, IF#2 Vendor Bulk)
- ✅ IF#2 has alt=0 (no endpoints) and alt=1 (with EP 0x03 OUT, EP 0x83 IN)
- ✅ EP0 OUT commands **WORKING**: SET_PROFILE, START_STREAM, STOP_STREAM all succeed
- ❌ **EP0 IN (GET_STATUS) BROKEN**: errno 110 timeout on EVERY attempt
- ❌ **IN endpoint (0x83) NOT TESTED**: Cannot test due to PyUSB alt=1 switch error

**Description**:
After device developer flashed new firmware, the Vendor Bulk interface (IF#2) has disappeared.

**Current State** (After Flashing):
```
✅ Device Configuration 1:
  Interface 0: CDC Control (class=2)
    EP 0x82 (IN, Interrupt)

  Interface 1: CDC Data (class=10)
    EP 0x01 (OUT, Bulk)
    EP 0x81 (IN, Bulk)

  Interface 2: Vendor Bulk (class=255)
    alt=0: bNumEndpoints=0 (initialization state)
    alt=1: bNumEndpoints=2
      EP 0x03 (OUT, Bulk)  ✅
      EP 0x83 (IN, Bulk)   ✅
```

**Problem Details** (CONFIRMED PERSISTENT 2025-10-21 ~19:00):
```
DEVICE STATUS CHECK (Re-verified):
- lsusb: Device 009 (was Device 008 - re-enumeration after testing)
- bNumInterfaces: 3 ✅
- Endpoints visible: 0x03 (OUT), 0x83 (IN) ✅

Test Results (CURRENT):
[tx] ✅ EP0 OUT commands WORK:
    - SET_PROFILE (0x14) ✅ (errno=0, successful)
    - Additional attempts: All succeed
    
[ep0] ❌ GET_STATUS (EP0 IN) - CONSISTENT FAILURES:
    - Attempt 1: errno 110 timeout ✗
    - Attempt 2: errno 110 timeout ✗
    - Attempt 3: errno 110 timeout ✗
    - 100% failure rate
    
[rx] ❌ IN endpoint (0x83) NOT TESTED:
    - Cannot establish alt=1 via PyUSB (error: "Other error")
    - Unknown if endpoint would receive data
```

**Timeline**:
- 18:34 - GET_STATUS: WORKING (returned 64 bytes) ✓
- 18:45 - GET_STATUS: BROKEN (errno 110 timeout) ✗
- 18:50 - GET_STATUS: Confirmed broken across multiple attempts ✗
- 19:00 - GET_STATUS: STILL BROKEN, device re-enumerated but issue persists ✗

**GitHub Status**:
- Last firmware commit: 2025-10-21 10:53 (Added BMI30.stm32h7.elf)
- Firmware deleted: 2025-10-21 15:37 (Delete firmware/BMI30.stm32h7.elf)
- No new firmware or updates since deletion ⏳

**Previous Test Results** (2025-10-21 ~18:34):
```
[ep0] ✅ STAT v1 readable (64 bytes, alt1=True, out_armed=True)
```

**Root Cause Analysis**:

✅ **What Works**:
- IF#2 USB descriptor correctly defined (class 255, 2 alt settings)
- alt=0→alt=1 switching functional (vendor SET_ALT command)
- Bulk endpoints (0x03/0x83) active on alt=1
- EP0 GET_STATUS working (STAT v1 readable)
- Firmware compilation and flashing successful

✅ **Fixed**:
- Device firmware **EP0 Bulk OUT handler** (control endpoint request handler)
- Commands now send successfully: SET_PROFILE (0x14), START_STREAM (0x20), etc.
- errno 5 I/O Error no longer appears

❌ **What's Broken Now** (PERSISTENT REGRESSION):
- **CRITICAL**: EP0 GET_STATUS (IN) is completely broken - 100% timeout rate (errno 110)
  - Persists across device re-enumeration
  - Does NOT recover even after STOP_STREAM command
  - Suggests: Hardware EP0 IN pipeline stuck or firmware handler crashed
- IN endpoint (0x83) cannot be tested due to PyUSB alt=1 switch error ("Other error")
  - Workaround needed: Use vendor SET_ALT control command instead of PyUSB
- Device firmware appears unstable or in corrupted state

**Likely Device Firmware Issues** (Updated):

✅ **Fixed** (as of 2025-10-21 ~17:37):
1. EP0 OUT data phase handler - NOW WORKING
2. Control transfer implementation - NOW WORKING
3. Command request validation - NOW WORKING

❌ **Needs Fixing**:
1. IN endpoint (0x83) data transmission not active
2. DMA/FIFO configuration for Bulk IN transfers
3. Data buffering/queuing after START_STREAM
4. May need additional initialization command
5. Check if device firmware actually triggers data stream on START_STREAM

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

### Action Items (For Device Developer)

**Firmware Status**:
- ✅ New firmware flashed successfully (2025-10-21 ~17:37)
- ✅ IF#2 Vendor Bulk interface now present
- ✅ Endpoints (0x03/0x83) accessible
- ❌ EP0 control request handler broken

**Issue Found**:
All EP0 Bulk OUT control commands fail with errno 5 (I/O Error).
This is a **firmware bug** that needs fixing, not a flashing issue.

**Action Required** (device developer):
1. ✅ Review device firmware source code
2. ✅ Find EP0 control OUT request handler implementation
3. ✅ Check:
   - Data phase handling for control transfers
   - Request parsing/validation logic
   - Endpoint HALT/stall conditions
   - Interrupt/DMA conflict on EP0
4. ✅ Fix the bug (likely in stm32 USB driver configuration)
5. ✅ Re-compile firmware
6. ✅ Re-flash device
7. ✅ Test: `python3 BMI30.200.py` should connect and stream data

**Expected Output After Fix**:
```
[open] ✅ IF#2 found
[alt] ✅ alt=1 set
[ep0] ✅ STAT v1 readable
[tx] ✅ Commands succeed (no errno 5!)
[stream] ✅ Data flowing from IN endpoint
[gui] ✅ Oscilloscope displays at ~200 FPS
```

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

### For Current Issue #1 (EP0 Command Handler):
- [x] ✅ Developer adds compiled firmware to repo (DONE: 2025-10-21 12:53)
- [x] ✅ Developer flashes device via ST-Link (DONE: 2025-10-21 ~17:37)
- [x] ✅ Device shows IF#2 Vendor Bulk (VERIFIED: 3 interfaces, alt=1 works)
- [ ] ⏳ Developer fixes EP0 Bulk OUT control request handler (IN PROGRESS)
- [ ] Developer re-compiles firmware with fix
- [ ] Developer re-flashes device with new binary
- [ ] Test: EP0 commands succeed (no errno 5)
- [ ] Host runs BMI30.200.py and streams data
- [ ] GUI displays ADC0 and ADC1 at ~200 FPS
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
