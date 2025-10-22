#!/usr/bin/env python3
from __future__ import annotations
import time
from typing import Optional
import usb.core, usb.util  # type: ignore

DEFAULT_VID = 0xCAFE
DEFAULT_PID = 0x4001
DEFAULT_IF = None  # если None — автопоиск интерфейса класса 0xFF

class VendorIO:
    def __init__(self, vid=DEFAULT_VID, pid=DEFAULT_PID, interface=DEFAULT_IF):
        self.dev = usb.core.find(idVendor=vid, idProduct=pid)
        if self.dev is None:
            raise RuntimeError('Vendor device not found')
        # Активная конфигурация
        try:
            cfg = self.dev.get_active_configuration()
        except Exception:
            self.dev.set_configuration()
            cfg = self.dev.get_active_configuration()
        # Отстыковать kernel драйверы для всех интерфейсов конфигурации (мягко)
        try:
            for intf in cfg:
                try:
                    if self.dev.is_kernel_driver_active(intf.bInterfaceNumber):
                        try: self.dev.detach_kernel_driver(intf.bInterfaceNumber)
                        except Exception: pass
                except Exception:
                    pass
        except Exception:
            pass
        # Поиск интерфейса: если задан номер — используем его; иначе ищем класс 0xFF
        chosen_intf = None
        ep_in = None
        ep_out = None
        if interface is not None:
            # найти по номеру
            for intf in cfg:
                if intf.bInterfaceNumber == interface:
                    chosen_intf = intf
                    break
        if chosen_intf is None:
            # сначала предпочтем интерфейс класса 0xFF
            for intf in cfg:
                try:
                    if intf.bInterfaceClass == 0xFF:
                        chosen_intf = intf
                        break
                except Exception:
                    continue
        if chosen_intf is None:
            raise RuntimeError('Vendor interface (class 0xFF) not found')
        # Выбор EP: любой bulk IN и bulk OUT
        for e in chosen_intf.endpoints():
            try:
                is_bulk = (e.bmAttributes & 0x03) == 2
                if not is_bulk:
                    continue
                if e.bEndpointAddress & 0x80:
                    ep_in = e.bEndpointAddress
                else:
                    ep_out = e.bEndpointAddress
            except Exception:
                continue
        if ep_in is None or ep_out is None:
            raise RuntimeError('Bulk IN/OUT endpoints not found on vendor interface')
        # Claim
        try:
            usb.util.claim_interface(self.dev, chosen_intf.bInterfaceNumber)
        except Exception:
            pass
        self.interface = chosen_intf.bInterfaceNumber
        self._ep_in = ep_in
        self._ep_out = ep_out
        self.timeout_ms = 200  # default read timeout
        # Serial-like attributes used by code
        self.baudrate = 2_000_000  # only for time estimates; not used by USB
        self._rx_buf = bytearray()

    # serial-like API
    @property
    def timeout(self) -> float:
        return self.timeout_ms / 1000.0

    @timeout.setter
    def timeout(self, v: float):
        self.timeout_ms = int(max(1.0, (v if v is not None else 0.2) * 1000))

    def read(self, n: int) -> bytes:
    # Serve from stash first
        if len(self._rx_buf) >= n:
            out = bytes(self._rx_buf[:n])
            del self._rx_buf[:n]
            return out
        # Otherwise, fetch from USB in chunks
        deadline = time.time() + (self.timeout_ms / 1000.0)
        while len(self._rx_buf) < n:
            try:
                chunk = bytes(self.dev.read(self._ep_in, 64, self.timeout_ms))
                if chunk:
                    self._rx_buf.extend(chunk)
                else:
                    if time.time() >= deadline:
                        break
            except usb.core.USBError as e:
                # Timeout or transient errors: break on timeout
                if getattr(e, 'errno', None) in (110,):  # ETIMEDOUT
                    if time.time() >= deadline:
                        break
                    continue
                # No such device => propagate
                raise
        take = min(n, len(self._rx_buf))
        out = bytes(self._rx_buf[:take])
        del self._rx_buf[:take]
        return out

    def write(self, data: bytes) -> int:
        return int(self.dev.write(self._ep_out, data, int(self.timeout_ms)))

    def flush(self):
        # Bulk has no flush concept; assume immediate
        return None

    def close(self):
        try:
            usb.util.release_interface(self.dev, self.interface)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass

def open_vendor(vid=DEFAULT_VID, pid=DEFAULT_PID) -> VendorIO:
    return VendorIO(vid, pid, DEFAULT_IF)
