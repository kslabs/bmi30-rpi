#!/usr/bin/env python3
from __future__ import annotations
import sys, time, struct
import usb.core, usb.util

VID=0xCAFE; PID=0x4001; EP_OUT=0x03; EP_IN=0x83
CMD_START=0x20; CMD_STOP=0x21; CMD_GET_STATUS=0x30
HDR_FMT='<H B B I I H H I I I H H'; HDR_SIZE=32; MAGIC=0xA55A; MAGIC_LE=b'\x5A\xA5'

def hexb(b: bytes, n=32):
    return ' '.join(f"{x:02X}" for x in b[:n]) + (" …" if len(b)>n else '')

def find_vendor():
    d = usb.core.find(idVendor=VID, idProduct=PID)
    if d is None: raise SystemExit('device not found')
    try:
        _=d.get_active_configuration()
    except usb.core.USBError:
        d.set_configuration()
    cfg=d.get_active_configuration()
    intf=None
    for i in cfg:
        eps=[e.bEndpointAddress for e in i.endpoints()]
        if EP_OUT in eps and EP_IN in eps:
            intf=i; break
    if intf is None:
        for i in cfg:
            cls=getattr(i,'bInterfaceClass',None)
            if cls==0xFF:
                eps=[e.bEndpointAddress for e in i.endpoints()]
                outs=[e for e in eps if (e&0x80)==0]; ins=[e for e in eps if (e&0x80)]
                if outs and ins:
                    intf=i; break
    if intf is None: raise SystemExit('vendor interface not found')
    try:
        if d.is_kernel_driver_active(intf.bInterfaceNumber): d.detach_kernel_driver(intf.bInterfaceNumber)
    except Exception: pass
    usb.util.claim_interface(d,intf.bInterfaceNumber)
    return d,intf


def parse_hdr(h: bytes):
    return struct.unpack(HDR_FMT, h)


def main():
    d,intf = find_vendor()
    print(f"[open] IF#{intf.bInterfaceNumber} OUT=0x{EP_OUT:02X} IN=0x{EP_IN:02X}")
    buf=bytearray(); got_test=False; pairs=0; waiting_status=False
    def rn(n=2048,t=1000):
        return bytes(d.read(EP_IN,n,timeout=t))
    def wc(c):
        return d.write(EP_OUT,bytes([c]),timeout=1000)

    # START
    wc(CMD_START); print('[TX] START')
    # Optional: send GET_STATUS right away to see if one STAT appears later
    # wc(CMD_GET_STATUS); waiting_status=True; print('[TX] GET_STATUS')

    t_end=time.time()+6.0
    while time.time()<t_end and pairs<3:
        try:
            data=rn(2048,1000)
        except usb.core.USBError as e:
            if getattr(e,'errno',None)==110: continue
            raise
        if not data: continue
        if data[:4]==b'STAT':
            tag='(GET_STATUS)' if waiting_status else '(mid)'
            print(f"[RX] STAT {tag} len={len(data)} head={hexb(data,16)}")
            waiting_status=False
            continue
        buf.extend(data)
        while True:
            if len(buf)<HDR_SIZE: break
            if not (buf[0]==0x5A and buf[1]==0xA5):
                idx=buf.find(MAGIC_LE)
                if idx==-1:
                    del buf[:max(0,len(buf)-1)]; break
                else:
                    del buf[:idx]
                    if len(buf)<HDR_SIZE: break
            hdr=bytes(buf[:HDR_SIZE])
            try:
                (magic,ver,flags,seq,ts,total,zc,z1o,z1l,r1,r2,crc)=parse_hdr(hdr)
            except struct.error:
                break
            if magic!=MAGIC:
                del buf[0]; continue
            fl=flags
            frame_len=HDR_SIZE+int(total)*2
            if len(buf)<frame_len: break
            if (fl&0x80) and total==8 and not got_test:
                print(f"[RX] TEST len={frame_len} ver={ver} flags=0x{fl:02X} seq={seq}")
                got_test=True; del buf[:frame_len]; continue
            ch='A' if (fl&0x01) else ('B' if (fl&0x02) else '?')
            print(f"[RX] {ch} len={frame_len} seq={seq & 0xFFFF} total={total}")
            if ch=='B': pairs+=1
            del buf[:frame_len]
            if pairs==1 and not waiting_status:
                wc(CMD_GET_STATUS); waiting_status=True; print('[TX] GET_STATUS')
    # STOP
    wc(CMD_STOP); print('[TX] STOP')
    try:
        st=rn(64,1000)
        if st[:4]==b'STAT': print(f"[RX] STAT (STOP) len={len(st)} head={hexb(st,16)}")
    except Exception as e:
        print('[..] STOP wait:',e)

    try:
        usb.util.release_interface(d,intf.bInterfaceNumber)
    finally:
        usb.util.dispose_resources(d)

if __name__=='__main__':
    main()
