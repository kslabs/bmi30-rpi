#!/usr/bin/env python3
from __future__ import annotations
import sys, time
import usb.core, usb.util

VID=0xCAFE; PID=0x4001

def to_hex(b: bytes, n=32):
    return ' '.join(f"{x:02X}" for x in b[:n]) + (" …" if len(b)>n else '')

def main():
    dev = usb.core.find(idVendor=VID, idProduct=PID)
    if dev is None:
        print('device not found'); return 2
    try:
        _ = dev.get_active_configuration()
    except usb.core.USBError:
        dev.set_configuration()
    cfg = dev.get_active_configuration()
    print(f"cfg={cfg.bConfigurationValue} with {cfg.bNumInterfaces} interfaces")
    candidates = []
    for intf in cfg:  # type: ignore
        print(f"IF#{intf.bInterfaceNumber} cls=0x{getattr(intf,'bInterfaceClass',0):02X} alt={intf.bAlternateSetting}")
        eps = list(intf.endpoints())
        for e in eps:
            print(f"  EP 0x{e.bEndpointAddress:02X} attr={e.bmAttributes} maxpkt={e.wMaxPacketSize}")
        if getattr(intf,'bInterfaceClass',None)==0xFF:
            outs=[e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80)==0 and (e.bmAttributes & 0x03)==2]
            ins =[e.bEndpointAddress for e in eps if (e.bEndpointAddress & 0x80)!=0 and (e.bmAttributes & 0x03)==2]
            if outs and ins:
                candidates.append((intf, outs, ins))
    if not candidates:
        print('no vendor bulk interfaces'); return 3
    print('\n[probe] trying START/GET_STATUS on each vendor IF...')
    for intf, outs, ins in candidates:
        print(f"-- IF#{intf.bInterfaceNumber} outs={list(map(hex,outs))} ins={list(map(hex,ins))}")
        try:
            if dev.is_kernel_driver_active(intf.bInterfaceNumber):
                try: dev.detach_kernel_driver(intf.bInterfaceNumber)
                except Exception: pass
        except Exception:
            pass
        usb.util.claim_interface(dev, intf.bInterfaceNumber)
        try:
            # send START to all outs
            for ep_out in outs:
                try:
                    n = dev.write(ep_out, bytes([0x20]), timeout=500)
                    print(f"  [TX] START -> EP_OUT 0x{ep_out:02X}, n={n}")
                except Exception as e:
                    print(f"  [TX] START EP 0x{ep_out:02X} err: {e}")
            # read a few from each in
            for ep_in in ins:
                for i in range(3):
                    try:
                        data = bytes(dev.read(ep_in, 2048, timeout=600))
                        head = to_hex(data,16)
                        tag = 'STAT' if data[:4]==b'STAT' else 'DATA'
                        print(f"  [RX] from EP_IN 0x{ep_in:02X} len={len(data)} tag={tag} head={head}")
                    except Exception as e:
                        print(f"  [RX] EP 0x{ep_in:02X} timeout {i}: {e}")
            # try GET_STATUS on outs
            for ep_out in outs:
                try:
                    dev.write(ep_out, bytes([0x30]), timeout=500)
                    print(f"  [TX] GET_STATUS on EP_OUT 0x{ep_out:02X}")
                except Exception as e:
                    print(f"  [TX] GET_STATUS EP 0x{ep_out:02X} err: {e}")
            for ep_in in ins:
                try:
                    data = bytes(dev.read(ep_in, 64, timeout=600))
                    head = to_hex(data,16)
                    tag = 'STAT' if data[:4]==b'STAT' else 'DATA'
                    print(f"  [RX] after GET_STATUS from 0x{ep_in:02X} len={len(data)} tag={tag} head={head}")
                except Exception as e:
                    print(f"  [RX] after GET_STATUS 0x{ep_in:02X} timeout: {e}")
        finally:
            try: usb.util.release_interface(dev, intf.bInterfaceNumber)
            except Exception: pass
    return 0

if __name__=='__main__':
    sys.exit(main())
