#!/usr/bin/env python3
import sys, time, argparse, usb.core, usb.util, struct

VID=0xCAFE
PID=0x4001
EP_IN=0x83
EP_OUT=0x03

CMD_SET_PROFILE   = 0x14
CMD_SET_FULL_MODE = 0x13
CMD_SET_FRAME_SAMPLES = 0x17
CMD_START_STREAM  = 0x20
CMD_STOP_STREAM   = 0x21
CMD_GET_STATUS    = 0x30

MAGIC=0xA55A
HDR_SIZE=32
VF_ADC0=0x01
VF_ADC1=0x02


def get_status(dev):
    try:
        data = dev.ctrl_transfer(0xC0, CMD_GET_STATUS, 0, 0, 64, timeout=300)
        return bytes(data) if data is not None else None
    except Exception:
        return None

def wait_ready(dev, timeout=0.8):
    t0=time.time()
    ok=False
    while time.time()-t0 < timeout:
        st = get_status(dev)
        if st and len(st) >= 64:
            ok=True
            break
        time.sleep(0.02)
    # clear halts either way
    try:
        usb.util.clear_halt(dev, EP_IN)
        usb.util.clear_halt(dev, EP_OUT)
    except Exception:
        pass
    return ok

def find_dev():
    d = usb.core.find(idVendor=VID, idProduct=PID)
    if not d:
        raise SystemExit(f"Device {VID:04x}:{PID:04x} not found")
    # choose interface with endpoints
    cfg = d.get_active_configuration()
    intf=None
    for it in cfg:
        eps=[e.bEndpointAddress for e in it.endpoints()]
        if EP_IN in eps and EP_OUT in eps:
            intf=it
            break
    if intf is None:
        # try any interface
        for it in cfg:
            try:
                for e in it.endpoints():
                    pass
            except Exception:
                continue
            intf=it; break
    if intf is None:
        raise SystemExit("No suitable interface")
    # claim and set alt=1 if possible
    try:
        if d.is_kernel_driver_active(intf.bInterfaceNumber):
            try:
                d.detach_kernel_driver(intf.bInterfaceNumber)
            except Exception:
                pass
    except Exception:
        pass
    try:
        usb.util.claim_interface(d, intf.bInterfaceNumber)
    except Exception:
        pass
    # alt=1 preferred
    try:
        d.set_interface_altsetting(interface=intf.bInterfaceNumber, alternate_setting=1)
    except Exception:
        pass
    # clear halt
    try:
        usb.util.clear_halt(d, EP_IN)
    except Exception:
        pass
    try:
        usb.util.clear_halt(d, EP_OUT)
    except Exception:
        pass
    # quick ready poll
    wait_ready(d, timeout=0.5)
    return d

def send_cmd(dev, cmd, payload=b""):
    pkt = bytes([cmd]) + payload
    dev.write(EP_OUT, pkt, timeout=1000)

def send_set_block_rate(dev, rate_hz:int):
    # vendor 0x11, payload u16 LE
    payload = struct.pack('<BH', 0x11, int(rate_hz) & 0xFFFF)
    dev.write(EP_OUT, payload, timeout=1000)


def parse_frames(stream: bytes, buf: bytearray, on_frame):
    buf.extend(stream)
    MAGIC_LE=b"\x5A\xA5"
    while True:
        if len(buf) < HDR_SIZE:
            return
        if not (buf[0] == 0x5A and buf[1] == 0xA5):
            idx = buf.find(MAGIC_LE)
            if idx == -1:
                del buf[:max(0, len(buf)-1)]
                return
            else:
                del buf[:idx]
                if len(buf) < HDR_SIZE:
                    return
        hdr = bytes(buf[:HDR_SIZE])
        try:
            (magic,ver,flags,seq,timestamp,total_samples,zone_count,zone1_offset,zone1_length,reserved,reserved2,crc16)= struct.unpack('<H B B I I H H I I I H H', hdr)
        except struct.error:
            return
        if magic != MAGIC:
            del buf[0]
            continue
        payload_len = int(total_samples)*2
        frame_total = HDR_SIZE + payload_len
        if len(buf) < frame_total:
            return
        payload = bytes(buf[HDR_SIZE:frame_total])
        del buf[:frame_total]
        # call handler
        on_frame(flags, seq, timestamp, total_samples, payload)


def run(profile:int, ns:int|None, rate:int|None, duration:float):
    dev = find_dev()
    print(f"[open] {dev.idVendor:04x}:{dev.idProduct:04x} IF ready")
    # clean start: STOP and clear
    try:
        send_cmd(dev, CMD_STOP_STREAM)
        time.sleep(0.02)
    except Exception:
        pass
    try:
        usb.util.clear_halt(dev, EP_IN)
        usb.util.clear_halt(dev, EP_OUT)
    except Exception:
        pass
    # alt toggle kick if needed
    try:
        # find interface number
        cfg = dev.get_active_configuration()
        intf_num = None
        for it in cfg:
            eps=[e.bEndpointAddress for e in it.endpoints()]
            if EP_IN in eps and EP_OUT in eps:
                intf_num = it.bInterfaceNumber
                break
        if intf_num is not None:
            dev.set_interface_altsetting(interface=intf_num, alternate_setting=0)
            time.sleep(0.005)
            dev.set_interface_altsetting(interface=intf_num, alternate_setting=1)
    except Exception:
        pass
    wait_ready(dev, timeout=0.6)

    # config
    try:
        send_cmd(dev, CMD_SET_FULL_MODE, bytes([1]))
        time.sleep(0.01)
    except Exception:
        pass
    send_cmd(dev, CMD_SET_PROFILE, bytes([profile & 0xFF])); time.sleep(0.01)
    # ⚠️ Контракт обновлён: оба профиля используют total_samples=912 (прошивка не поддерживает NS=1360 для профиля 1)
    # Поэтому не отправляем SET_FRAME_SAMPLES для профиля 1 (ломает передачу), только для профиля 2 если явно требуется
    if ns is not None and profile == 2:
        send_cmd(dev, CMD_SET_FRAME_SAMPLES, int(ns).to_bytes(2,'little')); time.sleep(0.01)
    if rate is not None:
        try:
            send_set_block_rate(dev, int(rate)); time.sleep(0.01)
        except Exception:
            pass
    send_cmd(dev, CMD_START_STREAM, b""); time.sleep(0.05)
    wait_ready(dev, timeout=0.6)
    
    # check status immediately after START
    st = get_status(dev)
    if st and len(st) >= 64:
        print(f"[stat] after START: len={len(st)}, header={st[:16]}")
    else:
        print(f"[stat] no status after START")

    buf = bytearray()
    t0 = time.time()
    a_times=[]; b_times=[]
    ns_counts={}
    total=0
    def on_frame(flags, seq, ts, total_samples, payload):
        nonlocal a_times, b_times, ns_counts, total
        total += 1
        ns_counts[int(total_samples)] = ns_counts.get(int(total_samples), 0) + 1
        if flags & VF_ADC0:
            a_times.append(time.time())
        elif flags & VF_ADC1:
            b_times.append(time.time())
    # read loop
    while time.time() - t0 < duration:
        try:
            data = bytes(dev.read(EP_IN, 2048, timeout=1000))
        except usb.core.USBError as e:
            if e.errno == 110: # timeout
                continue
            print("[usb] read err:", e)
            break
        if data:
            parse_frames(data, buf, on_frame)
    # stop
    try:
        send_cmd(dev, CMD_STOP_STREAM)
    except Exception:
        pass
    # stats
    print("Frames:", total)
    if ns_counts:
        print("NS counts:", ns_counts)
        most_ns = max(ns_counts.items(), key=lambda kv: kv[1])[0]
        print("Most common total_samples:", most_ns)
    else:
        print("No frames parsed")
    def rate_from(times):
        if len(times) < 3:
            return None
        dts = [t2-t1 for t1,t2 in zip(times, times[1:]) if t2>t1]
        if not dts:
            return None
        avg = sum(dts)/len(dts)
        return 1.0/avg if avg>0 else None
    rA = rate_from(a_times)
    rB = rate_from(b_times)
    print(f"A frames: {len(a_times)} rate≈{rA:.1f}Hz" if rA else f"A frames: {len(a_times)} rate=unknown")
    print(f"B frames: {len(b_times)} rate≈{rB:.1f}Hz" if rB else f"B frames: {len(b_times)} rate=unknown")

    usb.util.dispose_resources(dev)

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Diagnose block rate and total_samples')
    ap.add_argument('--profile', type=int, default=1, choices=[1,2])
    ap.add_argument('--ns', type=int, default=None)
    ap.add_argument('--rate', type=int, default=None)
    ap.add_argument('--duration', type=float, default=5.0)
    args = ap.parse_args()
    run(args.profile, args.ns, args.rate, args.duration)
