#!/usr/bin/env python3
import usb.core, usb.util, struct, time, threading, queue, sys, os
from collections import deque

VID=0xCAFE  # Автопоиск если не найдено
PID=0x4001
EP_IN=0x83  # vendor bulk IN (interface 2)
EP_OUT=0x03 # vendor bulk OUT (interface 2)

CMD_SET_PROFILE   = 0x14
CMD_SET_FULL_MODE = 0x13
CMD_SET_ROI_US    = 0x15
CMD_START_STREAM  = 0x20
CMD_STOP_STREAM   = 0x21
CMD_GET_STATUS    = 0x30
CMD_SET_FRAME_SAMPLES = 0x17
CMD_SET_ALT       = 0x31  # optional vendor EP0 control OUT to set alt
CMD_SOFT_RESET   = 0x7E  # EP0 vendor control OUT, no data
CMD_DEEP_RESET   = 0x7F  # EP0 vendor control OUT, no data

MAGIC=0xA55A
HDR_FMT='<HBBI I H H I I I H H'  # manual split
# We'll unpack manually due to spacing: (magic,ver,flags,seq,timestamp,total_samples,zone_count,zone1_offset,zone1_length,reserved,reserved2,crc16)
HDR_SIZE=32

VF_ADC0   =0x01
VF_ADC1   =0x02
VF_CRC    =0x04

def crc16_ccitt_false(data:bytes, init=0xFFFF):
    crc=init
    for b in data:
        crc ^= b<<8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc<<1) ^ 0x1021
            else:
                crc <<=1
            crc &=0xFFFF
    return crc

class Frame:
    __slots__=("seq","timestamp","adc_id","flags","samples","payload")
    def __init__(self,seq,timestamp,adc_id,flags,samples,payload):
        self.seq=seq; self.timestamp=timestamp; self.adc_id=adc_id; self.flags=flags; self.samples=samples; self.payload=payload

class StereoAssembler:
    def __init__(self):
        self.bufA={}; self.bufB={}; self.q=queue.Queue(maxsize=256)
        try:
            self.relaxed = str(os.getenv('BMI30_RELAXED_PAIRING','1')).lower() not in ('0','false','no')
        except Exception:
            self.relaxed = True
    def _emit_pair(self, a: 'Frame', b: 'Frame'):
        try:
            self.q.put((a, b))
        except Exception:
            pass
    def push(self,f:Frame):
        if f.adc_id==0:
            self.bufA[f.seq]=f
            if f.seq in self.bufB:
                a=self.bufA.pop(f.seq); b=self.bufB.pop(f.seq)
                self._emit_pair(a,b)
            elif self.relaxed and (f.seq+1) in self.bufB:
                # Допуск: устройство может инкрементировать seq на каждом кадре (A->B)
                a=self.bufA.pop(f.seq); b=self.bufB.pop(f.seq+1)
                self._emit_pair(a,b)
        else:
            self.bufB[f.seq]=f
            if f.seq in self.bufA:
                a=self.bufA.pop(f.seq); b=self.bufB.pop(f.seq)
                self._emit_pair(a,b)
            elif self.relaxed and (f.seq-1) in self.bufA:
                a=self.bufA.pop(f.seq-1); b=self.bufB.pop(f.seq)
                self._emit_pair(a,b)
        # Простейшая защита от разрастания при редких несостыковках
        if len(self.bufA) > 2048:
            self.bufA.clear()
        if len(self.bufB) > 2048:
            self.bufB.clear()

class USBStream:
    def __init__(self, profile=1, full=True, vid=VID, pid=PID, interactive=False, allow_any=False, iface_prefer=None, test_as_data: bool=False, frame_samples: int | None = None):
        self._running = True
        self.dev=None
        self.intf=None
        self.profile = profile
        self.full = full
        self.test_as_data = test_as_data
        self.frame_samples = frame_samples
        # функция сканирования всех интерфейсов устройства
        def scan_device(dev):
            infos=[]
            for cfg in dev:
                for intf in cfg:  # Interface
                    # intf сам уже alt setting (PyUSB объединяет)
                    eps=[e.bEndpointAddress for e in intf.endpoints()]
                    if EP_IN in eps and EP_OUT in eps:
                        infos.append((cfg.bConfigurationValue, intf.bInterfaceNumber, eps))
            return infos
        # 1. Ищем только указанный VID/PID (строго). Если нужно любое устройство, передать allow_any=True
        if vid and pid:
            exact_list=list(usb.core.find(find_all=True, idVendor=vid, idProduct=pid))
            if exact_list:
                # выбираем первое; если iface_prefer задан – ищем интерфейс по номеру
                self.dev=exact_list[0]
                matches=scan_device(self.dev)
                if not matches:
                    raise SystemExit(f"Найдено устройство, но нет подходящих интерфейсов с EP {hex(EP_IN)}/{hex(EP_OUT)}")
                if iface_prefer is not None:
                    m2=[m for m in matches if m[1]==iface_prefer]
                    if m2: matches=m2
                cfg_val,intf_num,eps=matches[0]
                self.intf_sel=(cfg_val,intf_num)
                print(f"[open] exact {hex(self.dev.idVendor)}:{hex(self.dev.idProduct)} cfg={cfg_val} intf={intf_num} eps={list(map(hex,eps))}")
        if self.dev is None and not allow_any:
            raise SystemExit(f"Device {hex(vid)}:{hex(pid)} not present. Подключите/прошивка? Либо запустите с allow_any=True для авто-поиска других.")
        # 2. Автопоиск по любому устройству (если разрешено)
        if self.dev is None and allow_any:
            cand=[]
            for d in usb.core.find(find_all=True):
                try: matches=scan_device(d)
                except Exception: continue
                if matches: cand.append((d,matches))
            if not cand:
                raise SystemExit("Нет ни одного устройства с подходящими endpoint'ами")
            if len(cand)>1 and interactive:
                print('[auto-any] Кандидаты:')
                for i,(d,ms) in enumerate(cand):
                    print(f"  {i}: {hex(d.idVendor)}:{hex(d.idProduct)} ifaces={[ (c,i2,[hex(e) for e in eps]) for (c,i2,eps) in ms ]}")
                sel=None
                while sel is None:
                    try:
                        sel=int(input('Выбор: '))
                        if sel<0 or sel>=len(cand): sel=None
                    except Exception: sel=None
                self.dev,matches=cand[sel]
            else:
                self.dev,matches=cand[0]
            self.intf_sel=(matches[0][0], matches[0][1])
            print(f"[auto-any] selected {hex(self.dev.idVendor)}:{hex(self.dev.idProduct)} cfg={self.intf_sel[0]} intf={self.intf_sel[1]}")
        # 3. (опционально) Жёсткий reset USB-устройства по требованию окружения
        try:
            _reset_on_connect = str(os.getenv('BMI30_USB_RESET_ON_CONNECT','0')).lower() not in ('0','false','no')
        except Exception:
            _reset_on_connect = False
        if _reset_on_connect:
            try:
                print('[usb] dev.reset() on connect (BMI30_USB_RESET_ON_CONNECT=1)')
                self.dev.reset()
                time.sleep(0.2)
            except Exception as e:
                print('[usb] dev.reset() failed:', e)

        # 4. Установка конфигурации и отделение драйвера (если занято)
        tried_detach=False
        cfg_val=self.intf_sel[0]
        chosen_intf_num = self.intf_sel[1]
        # Если нужная конфигурация уже активна — не трогаем
        try:
            cfg_active = self.dev.get_active_configuration()
        except usb.core.USBError:
            cfg_active = None
        need_set_config = not (cfg_active and cfg_active.bConfigurationValue == cfg_val)
        if need_set_config:
            while True:
                try:
                    # Мягко отсоединим драйвер только у выбранного vendor-интерфейса
                    try:
                        if self.dev.is_kernel_driver_active(chosen_intf_num):
                            try:
                                self.dev.detach_kernel_driver(chosen_intf_num)
                            except Exception:
                                pass
                    except Exception:
                        pass
                    self.dev.set_configuration(cfg_val)
                    break
                except usb.core.USBError as e:
                    if getattr(e,'errno',None)==16 and not tried_detach: # EBUSY
                        tried_detach=True
                        # Повторим попытку, предварительно отключив драйвер только выбранного интерфейса
                        try:
                            if self.dev.is_kernel_driver_active(chosen_intf_num):
                                try:
                                    self.dev.detach_kernel_driver(chosen_intf_num)
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        continue
                    if getattr(e,'errno',None)==13:
                        print('[perm] Недостаточно прав (udev?). Создайте правило:')
                        print(f'SUBSYSTEM=="usb", ATTR{{idVendor}}=="{self.dev.idVendor:04x}", ATTR{{idProduct}}=="{self.dev.idProduct:04x}", MODE="0666"')
                    raise
        # Ensure interface is released before claiming
        try:
            usb.util.release_interface(self.dev, chosen_intf_num)
        except Exception:
            pass
        # Claim the interface for bulk transfers
        try:
            usb.util.claim_interface(self.dev, chosen_intf_num)
        except Exception:
            pass
        # Clear halt on endpoints to ensure they are ready
        try:
            usb.util.clear_halt(self.dev, EP_OUT)
            usb.util.clear_halt(self.dev, EP_IN)
        except Exception:
            pass
        # 5. Получаем интерфейс и endpoints
        try:
            cfg=self.dev.get_active_configuration()
        except usb.core.USBError as ge:
            print('[err] cannot get active configuration:', ge)
            raise
        intf_num=self.intf_sel[1]
        self.intf_num = intf_num
                # Явно выбираем altsetting=1 для Vendor IF#2, где находятся bulk EP (новая прошивка)
        self.current_alt = 0
        self._ensure_alt(intf_num, desired_alt=1)
        # Найдём дескриптор интерфейса с alt=0
        intf = usb.util.find_descriptor(
            cfg,
            custom_match=lambda i: getattr(i, 'bInterfaceNumber', -1) == intf_num and getattr(i, 'bAlternateSetting', -1) == 0
        )
        if intf is None:
            # Попробуем найти любой alt для указанного интерфейса (fallback)
            intf = usb.util.find_descriptor(cfg, bInterfaceNumber=intf_num)
        if intf is None:
            raise SystemExit('Interface disappeared')
        # But take EP from alt=1
        intf_alt1 = usb.util.find_descriptor(
            cfg,
            custom_match=lambda i: getattr(i, 'bInterfaceNumber', -1) == intf_num and getattr(i, 'bAlternateSetting', -1) == 1
        )
        if intf_alt1:
            intf = intf_alt1
        # Запомним актуальный altsetting выбранного интерфейса
        try:
            self.alt_setting = getattr(intf, 'bAlternateSetting', 0)
        except Exception:
            self.alt_setting = 0
        # вытащим endpoints из текущего altsetting
        self.ep_in=None; self.ep_out=None
        for e in intf.endpoints():
            if e.bEndpointAddress==EP_IN: self.ep_in=e
            if e.bEndpointAddress==EP_OUT: self.ep_out=e
        if not (self.ep_in and self.ep_out):
            # Fallback: if EP not found and we didn't try alt=1 yet, try setting alt=1
            if self.current_alt != 1:
                print(f"[fallback] EP not found in alt={self.alt_setting}, trying alt=1")
                self._ensure_alt(intf_num, desired_alt=1)
                if self.current_alt == 1:
                    intf = usb.util.find_descriptor(
                        cfg,
                        custom_match=lambda i: getattr(i, 'bInterfaceNumber', -1) == intf_num and getattr(i, 'bAlternateSetting', -1) == 1
                    )
                    if intf:
                        self.ep_in=None; self.ep_out=None
                        for e in intf.endpoints():
                            if e.bEndpointAddress==EP_IN: self.ep_in=e
                            if e.bEndpointAddress==EP_OUT: self.ep_out=e
                        if self.ep_in and self.ep_out:
                            self.alt_setting = 1
                            print(f"[fallback] EP found in alt=1")
                            # Try to set alt=1 now
                            try:
                                self.dev.set_interface_altsetting(interface=intf_num, alternate_setting=1)
                                self.current_alt = 1
                                print(f"[alt] set alt=1 after EP found")
                            except Exception as e:
                                print(f"[alt] failed to set alt=1 after EP found: {e}")
                        else:
                            raise SystemExit(f'Endpoints {hex(EP_IN)}/{hex(EP_OUT)} not found even in alt=1')
                    else:
                        raise SystemExit('Interface alt=1 not found')
                else:
                    raise SystemExit(f'Endpoints {hex(EP_IN)}/{hex(EP_OUT)} not found in chosen interface/alt={self.alt_setting}')
            else:
                raise SystemExit(f'Endpoints {hex(EP_IN)}/{hex(EP_OUT)} not found in chosen interface/alt={self.alt_setting}')
        # Попробуем подготовить «чистый старт»: STOP, очистка состояний EP, переустановка altsetting
        try:
            _disable_clean = str(os.getenv('BMI30_CLEAN_START','1')).lower() in ('0','false','no')
        except Exception:
            _disable_clean = False
        if not _disable_clean:
            try:
                self._prepare_clean_start(stop_first=True)
            except Exception:
                pass

        # инициализация потоков (внутри __init__)
        self.disconnected = False
        self.connected_t = time.time()
        self.last_rx_t = self.connected_t
        self.last_restart_t = 0.0
        # Сохраним порт info для power cycle
        self.port_info = self.get_port_path_info()
        # Старт: отправим профиль/режим/размер кадра (если заданы), затем START
        try:
            # Небольшая проверка готовности перед первыми bulk OUT
            try:
                self._wait_ready(timeout=1.0)
            except Exception:
                pass
            try:
                if self.profile is not None:
                    self.send_cmd(CMD_SET_PROFILE, bytes([int(self.profile) & 0xFF])); time.sleep(0.02)
            except Exception:
                pass
            try:
                self.send_cmd(CMD_SET_FULL_MODE, bytes([1 if self.full else 0])); time.sleep(0.02)
            except Exception:
                pass
            if self.frame_samples is not None:
                try:
                    # u16 LE
                    ns = max(1, int(self.frame_samples)) & 0xFFFF
                    self.send_cmd(CMD_SET_FRAME_SAMPLES, ns.to_bytes(2, 'little'))
                    time.sleep(0.02)
                except Exception:
                    pass
            self.send_cmd(CMD_START_STREAM, b"")
            time.sleep(0.02)
            # EP0 статус-пинг сразу после старта
            self._get_status_ep0()
        except Exception:
            pass
    # Консервативный старт: без дополнительных пинков/GET_STATUS (сделаем только по запросу)
        self.lock = threading.Lock()
        self.frames = 0; self.bytes = 0; self.crc_bad = 0; self.magic_bad = 0
        self.test_seen = 0
        self.last_stat = None
        self.asm = StereoAssembler()
        self.stat_t = time.time()
        self.th = threading.Thread(target=self._rx_loop, daemon=True)
        self.th.start()
        self._fallback_done = False
        self._working_seen = False
        self.keepalive_last = self.connected_t
        self.restart_attempts = 0
        try:
            self.force_reopen = str(os.getenv('BMI30_FORCE_REOPEN','1')).lower() not in ('0','false','no')
        except Exception:
            self.force_reopen = True

    def _parse_stat_ready(self, st: bytes) -> tuple[bool, bool]:
        """Парсим STAT, возвращаем (alt1, out_armed). Безопасно при любом буфере."""
        try:
            if not isinstance(st, (bytes, bytearray)) or len(st) < 64 or st[:4] != b'STAT':
                return (False, False)
            flags2 = int.from_bytes(st[50:52], 'little')
            alt1 = ((flags2 >> 15) & 1) == 1
            # STAT v1: reserved2 @53
            reserved2 = st[53]
            out_armed = ((reserved2 >> 7) & 1) == 1
            return (alt1, out_armed)
        except Exception:
            return (False, False)

    def _wait_ready(self, timeout: float = 1.0):
        """Дождаться готовности устройства (alt=1 и out_armed=1 по STAT v1).
        Опрос EP0 каждые 5–10 мс до timeout. После успеха — CLEAR_HALT."""
        t0 = time.time()
        ready = False
        poll_int = 0.007  # ~7 мс между опросами
        max_to = max(0.05, float(timeout))
        
        while time.time() - t0 < max_to:
            try:
                self._get_status_ep0()
                st = getattr(self, 'last_stat', None)
                if st and len(st) >= 64:
                    alt1, out_armed = self._parse_stat_ready(st)
                    if alt1 and out_armed:
                        ready = True
                        break
            except Exception:
                pass
            time.sleep(poll_int)
        
        # После успеха или таймаута сделать CLEAR_HALT
        try:
            self._clear_halt_eps()
        except Exception:
            pass
        
        if not ready:
            try:
                print(f'[ep0] wait_ready: готовность не достигнута за {time.time()-t0:.3f}с')
            except Exception:
                pass
        return ready

    def _get_status_ep0(self):
        """Попробовать прочитать статус через EP0 (vendor control IN, recipient: device)."""
        try:
            # bmRequestType: 0xC0 (Device to Host, Vendor, Device)
            # bRequest: CMD_GET_STATUS
            # wValue: 0
            # wIndex: 0 (device)
            # wLength: 64
            data = None
            try:
                data = self.dev.ctrl_transfer(0xC0, CMD_GET_STATUS, 0, 0, 64, timeout=300)
            except usb.core.USBError as e:
                # Время от времени устройство может NAK/STALL — это нормально
                try:
                    if e.errno not in (110,):
                        print('[ep0] GET_STATUS usb err:', e)
                except Exception:
                    pass
                return
            if data is not None and len(data) > 0:
                bs = bytes(data)
                self.last_stat = bs
                print('[ep0] status len=', len(bs))
        except Exception as e:
            try:
                print('[ep0] GET_STATUS failed:', e)
            except Exception:
                pass

    def _clear_halt_eps(self):
        try:
            usb.util.clear_halt(self.dev, EP_IN)
        except Exception:
            pass
        try:
            usb.util.clear_halt(self.dev, EP_OUT)
        except Exception:
            pass

    def _reset_altsetting(self):
        try:
            _disable_alt = str(os.getenv('BMI30_RESET_ALT','1')).lower() in ('0','false','no')
        except Exception:
            _disable_alt = False
        if _disable_alt:
            return
        try:
            if hasattr(self, 'intf_num') and self.intf_num is not None:
                # Тоггл alt 0 -> 1 для мягкого переинициализирования пайплайна
                self._ensure_alt(self.intf_num, desired_alt=0)
                time.sleep(0.005)
                self._ensure_alt(self.intf_num, desired_alt=1)
        except Exception as e:
            try:
                print('[alt] set_interface_altsetting failed:', e)
            except Exception:
                pass

    def _prepare_clean_start(self, stop_first: bool = True):
        try:
            _disable_clean = str(os.getenv('BMI30_CLEAN_START','1')).lower() in ('0','false','no')
        except Exception:
            _disable_clean = False
        if _disable_clean:
            return
        # На всякий случай остановим поток на устройстве, затем почистим EP и altsetting
        if stop_first:
            try:
                # перед отправкой STOP дождёмся готовности
                self._wait_ready(timeout=1.0)
                self.send_cmd(CMD_STOP_STREAM, b"")
                time.sleep(0.02)
            except Exception:
                pass
        self._clear_halt_eps()
        # Небольшая пауза перед переустановкой altsetting
        time.sleep(0.01)
        self._reset_altsetting()
        # после смены альта дождёмся готовности
        try:
            self._wait_ready(timeout=0.5)
        except Exception:
            pass
        # И ещё раз очистим HALT на случай, если altsetting переинициализировал пайпы
        self._clear_halt_eps()

    def _kick_cdc_start(self):
        try:
            cfg2 = self.dev.get_active_configuration()
            cdc_intf = None; cdc_out = None
            for it in cfg2:
                try:
                    if getattr(it, 'bInterfaceClass', None) == 0x0A:  # CDC Data
                        for e in it.endpoints():
                            if (e.bEndpointAddress & 0x80) == 0 and (e.bmAttributes & 0x03) == 2:
                                cdc_intf = it; cdc_out = e.bEndpointAddress; break
                except Exception:
                    continue
                if cdc_out is not None:
                    break
            if cdc_out is not None and cdc_intf is not None:
                try:
                    usb.util.claim_interface(self.dev, cdc_intf.bInterfaceNumber)
                except Exception:
                    pass
                try:
                    _ = self.dev.write(cdc_out, bytes([CMD_START_STREAM]), timeout=300)
                    print("[kick] CDC START sent")
                except Exception as e:
                    print("[kick] CDC write failed:", e)
                try:
                    usb.util.release_interface(self.dev, cdc_intf.bInterfaceNumber)
                except Exception:
                    pass
        except Exception:
            pass

    def restart_stream(self, full=True):
        """Повторно пнуть поток, если устройство молчит."""
        try:
            # Чистый рестарт: остановить, очистить и только потом запускать
            self._prepare_clean_start(stop_first=True)
            if full:
                self.send_cmd(CMD_SET_FULL_MODE, bytes([1])); time.sleep(0.02)
            self.send_cmd(CMD_START_STREAM, b""); time.sleep(0.02)
            self._prime_get_status()
            self._kick_cdc_start()
            self.last_restart_t = time.time()
            print("[kick] restart_stream done")
        except Exception as e:
            print("[kick] restart_stream failed:", e)
    def _prime_get_status(self):
        try:
            for _ in range(2):
                self._get_status_ep0()
                time.sleep(0.05)
        except Exception:
            pass
    def _do_fallback_start(self):
        """Единовременный мягкий пинок потока, если видим только STAT/тишину."""
        if self._fallback_done:
            return
        try:
            self.send_cmd(CMD_SET_PROFILE, bytes([self.profile])); time.sleep(0.02)
        except Exception:
            pass
        try:
            self.send_cmd(CMD_SET_FULL_MODE, bytes([1 if self.full else 0])); time.sleep(0.02)
        except Exception:
            pass
        try:
            self.send_cmd(CMD_START_STREAM, b""); time.sleep(0.02)
        except Exception:
            pass
        # Попробуем дополнительно CDC START (если есть CDC Data интерфейс)
        try:
            self._kick_cdc_start()
        except Exception:
            pass
        self._fallback_done = True
    def close(self):
        self._running = False
        try:
            self.send_cmd(CMD_STOP_STREAM,b"")
        except Exception:
            pass
        # Переведём IF в alt=0 (idle), если возможно
        try:
            if hasattr(self, 'intf_num') and self.intf_num is not None:
                try:
                    usb.util.claim_interface(self.dev, self.intf_num)
                except Exception:
                    pass
                try:
                    self.dev.set_interface_altsetting(interface=self.intf_num, alternate_setting=0)
                    self.current_alt = 0
                except Exception:
                    pass
        except Exception:
            pass
        # Освободим интерфейс и очистим ресурсы, чтобы следующий запуск был «с нуля»
        try:
            if hasattr(self, 'intf_num') and self.intf_num is not None:
                try:
                    usb.util.release_interface(self.dev, self.intf_num)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            usb.util.dispose_resources(self.dev)
        except Exception:
            pass
    def soft_reset(self):
        """Отправить EP0 SOFT_RESET (0x7E) вендорским control OUT без данных."""
        try:
            self.dev.ctrl_transfer(0x40, CMD_SOFT_RESET, 0, 0, None, timeout=500)
            print('[ep0] SOFT_RESET sent')
        except Exception as e:
            print('[ep0] SOFT_RESET failed:', e)
            raise
    def deep_reset(self):
        """Отправить EP0 DEEP_RESET (0x7F) вендорским control OUT без данных."""
        try:
            self.dev.ctrl_transfer(0x40, CMD_DEEP_RESET, 0, 0, None, timeout=800)
            print('[ep0] DEEP_RESET sent')
        except Exception as e:
            print('[ep0] DEEP_RESET failed:', e)
            raise
    def set_alt(self, alt:int):
        """Принудительно установить altsetting интерфейса vendor (обычно 0 или 1)."""
        if not hasattr(self, 'intf_num') or self.intf_num is None:
            return
        self._ensure_alt(self.intf_num, desired_alt=int(alt))

    # --- internals ---
    def _ensure_alt(self, intf_num:int, desired_alt:int, retries:int=2):
        """Установить alt: стандартный SET_INTERFACE (0x0B) как основной, вендор SET_ALT(0x31) как fallback.
        После успеха — дождаться alt1/out_armed и сделать CLEAR_HALT."""
        # === Попытка 1: стандартный SET_INTERFACE (preferred) ===
        for attempt in range(retries+1):
            try:
                try:
                    if self.dev.is_kernel_driver_active(intf_num):
                        try:
                            self.dev.detach_kernel_driver(intf_num)
                        except Exception:
                            pass
                except Exception:
                    pass
                try:
                    usb.util.claim_interface(self.dev, intf_num)
                except Exception:
                    pass
                time.sleep(0.002)
                self.dev.set_interface_altsetting(interface=intf_num, alternate_setting=int(desired_alt))
                self.current_alt = int(desired_alt)
                print(f"[alt] set_interface_altsetting alt={desired_alt} ok (attempt {attempt+1})")
                # После успешного alt — дождёмся готовности и сделаем CLEAR_HALT
                try:
                    self._wait_ready(timeout=0.2)
                    self._clear_halt_eps()
                except Exception:
                    pass
                return
            except Exception as e:
                if attempt == retries:
                    try:
                        print(f"[alt] set_interface_altsetting alt={desired_alt} failed after {retries+1} attempts:", e)
                    except Exception:
                        pass
                try:
                    usb.util.release_interface(self.dev, intf_num)
                except Exception:
                    pass
                time.sleep(0.02)
        # === Попытка 2: стандартный control SET_INTERFACE (0x0B/0x01) ===
        try:
            bm = 0x01  # Host-to-Device, Standard, Interface
            REQ_SET_INTERFACE = 0x0B
            self.dev.ctrl_transfer(bm, REQ_SET_INTERFACE, int(desired_alt), int(intf_num), None, timeout=300)
            self.current_alt = int(desired_alt)
            print(f"[alt] ctrl SET_INTERFACE (0x0B/0x01) alt={desired_alt} ok")
            try:
                self._wait_ready(timeout=0.2)
                self._clear_halt_eps()
            except Exception:
                pass
            return
        except Exception as e:
            try:
                print(f"[alt] ctrl SET_INTERFACE (0x0B/0x01) alt={desired_alt} failed:", e)
            except Exception:
                pass
        # === Попытка 3: вендорский SET_ALT (0x31) как fallback ===
        try:
            # Device (0x40) с wIndex=2 — согласно спецификации прошивки
            try:
                self.dev.ctrl_transfer(0x40, CMD_SET_ALT, int(desired_alt), int(intf_num), None, timeout=300)
                self.current_alt = int(desired_alt)
                print(f"[alt] vendor SET_ALT(0x40) alt={desired_alt} ok")
                try:
                    self._wait_ready(timeout=0.2)
                    self._clear_halt_eps()
                except Exception:
                    pass
                return
            except Exception:
                pass
            # Interface (0x41) с wIndex=2 как дополнительная попытка
            try:
                self.dev.ctrl_transfer(0x41, CMD_SET_ALT, int(desired_alt), int(intf_num), None, timeout=300)
                self.current_alt = int(desired_alt)
                print(f"[alt] vendor SET_ALT(0x41) alt={desired_alt} ok")
                try:
                    self._wait_ready(timeout=0.2)
                    self._clear_halt_eps()
                except Exception:
                    pass
                return
            except Exception:
                pass
        except Exception as ee:
            try:
                print('[alt] vendor SET_ALT fallback failed:', ee)
            except Exception:
                pass
        # На ошибку
        try:
            print(f"[alt] unable to set alt={desired_alt} (all methods failed)")
        except Exception:
            pass
    def send_cmd(self, cmd, payload:bytes):
        pkt = bytes([cmd])+payload
        last_err=None
        for i in range(3):
            try:
                n = self.dev.write(EP_OUT, pkt, timeout=1000)
                print(f"[tx] cmd=0x{cmd:02X} n={n}")
                return
            except Exception as e:
                last_err=e
                print(f"[tx-err] cmd=0x{cmd:02X} try={i+1} err={e}")
                # Если EIO/STALL/EPIPE — проверим готовность, снимем HALT и повторим ожидание
                try:
                    eno = getattr(e, 'errno', None)
                except Exception:
                    eno = None
                if eno in (5, 32) or 'EPIPE' in str(e) or 'Input/Output' in str(e):
                    try:
                        self._get_status_ep0()
                        st = getattr(self, 'last_stat', None)
                        if st and len(st) >= 64:
                            alt1, out_armed = self._parse_stat_ready(st)
                            print(f"[tx-diag] alt1={alt1}, out_armed={out_armed} → CLEAR_HALT + retry")
                    except Exception:
                        pass
                    try:
                        self._clear_halt_eps()
                        # подождём готовности alt1/out_armed
                        self._wait_ready(timeout=0.2)
                    except Exception:
                        pass
                time.sleep(0.05)
        # Если это EBUSY — пометим как отключение, чтобы верхний уровень переподключился
        try:
            if isinstance(last_err, usb.core.USBError) and getattr(last_err, 'errno', None) == 16:
                self.disconnected = True
        except Exception:
            pass
        print(f"[tx-err] cmd=0x{cmd:02X} failed after retries: {last_err}")
    def _rx_loop(self):
        buf = bytearray()
        MAGIC_LE = b"\x5A\xA5"
        while self._running and not self.disconnected:
            try:
                data = bytes(self.dev.read(EP_IN, 4096, timeout=1000))
            except usb.core.USBError as e:
                if e.errno == 110: # timeout
                    # При длительном отсутствии рабочих кадров попробуем единоразовый fallback
                    now_t = time.time()
                    if (not self._working_seen) and (not self._fallback_done) and (now_t - self.connected_t > 1.6):
                        self._do_fallback_start()
                    # Keepalive/мягкий рестарт: если давно не было вообще RX
                    if (now_t - self.last_rx_t) > 2.0 and (now_t - self.keepalive_last) > 1.0:
                        # EP0 keepalive, даже если bulk OUT залип
                        self._get_status_ep0()
                        self.keepalive_last = now_t
                    if (now_t - self.last_rx_t) > 4.0 and (now_t - self.last_restart_t) > 3.0:
                        try:
                            # Выполним мягкий «чистый» рестарт: STOP + очистка EP + переустановка altsetting
                            self._prepare_clean_start(stop_first=True)
                            try:
                                if self.profile is not None:
                                    self.send_cmd(CMD_SET_PROFILE, bytes([int(self.profile) & 0xFF])); time.sleep(0.02)
                            except Exception:
                                pass
                            try:
                                self.send_cmd(CMD_SET_FULL_MODE, bytes([1 if self.full else 0])); time.sleep(0.02)
                            except Exception:
                                pass
                            if self.frame_samples is not None:
                                try:
                                    ns = max(1, int(self.frame_samples)) & 0xFFFF
                                    self.send_cmd(CMD_SET_FRAME_SAMPLES, ns.to_bytes(2,'little'))
                                    time.sleep(0.02)
                                except Exception:
                                    pass
                            self.send_cmd(CMD_START_STREAM, b""); time.sleep(0.02)
                            self._prime_get_status()
                            self._kick_cdc_start()
                            self.last_restart_t = time.time()
                            self.restart_attempts += 1
                            print("[kick] gentle restart (no RX)")
                        except Exception as e2:
                            print("[kick] gentle restart failed:", e2)
                        # По достижении нескольких неудачных рестартов можно попробовать жёсткий reset устройства (опционально)
                        try:
                            import os as _os
                            if self.restart_attempts >= 3 and str(_os.getenv('BMI30_USB_HARD_RESET','0')).lower() not in ('0','false','no'):
                                print('[reset] Performing usb device reset()')
                                try:
                                    self.dev.reset()
                                except Exception as _e:
                                    print('[reset] dev.reset() failed:', _e)
                                self.restart_attempts = 0
                        except Exception:
                            pass
                        # Или принудительно инициировать полное переподключение на верхнем уровне
                        if self.restart_attempts >= 3 and getattr(self, 'force_reopen', True):
                            print('[reopen] Marking stream as disconnected to force full reopen')
                            self.disconnected = True
                            break
                    continue
                # fatal disconnect codes: 5=EIO, 19=ENODEV, 32=EPIPE
                if e.errno in (5,19,32):
                    print(f"[disconnect] USB error {e.errno} => stop loop")
                    self.disconnected=True
                    break
                # 16=EBUSY: транзиентная занятость — подождём и продолжим
                if e.errno == 16:
                    print(f"[busy] USB error {e.errno} (Resource busy)")
                    time.sleep(0.05)
                    continue
                print("USB err", e); time.sleep(0.1); continue
            # перехват STAT коротких пакетов: выкусываем подряд и оставляем хвост
            if data:
                mv = memoryview(data)
                pos = 0
                n = len(mv)
                while pos + 4 <= n and mv[pos:pos+4] == b'STAT':
                    if pos + 64 <= n:
                        self.last_stat = bytes(mv[pos:pos+64])
                        pos += 64
                        continue
                    # если STAT неполный (маловероятно) — не трогаем, ждём доклейку
                    break
                if pos < n:
                    buf.extend(mv[pos:].tobytes())
            if data:
                self.last_rx_t = time.time()
            # выкидываем STAT пакеты как отдельные короткие сообщения
            # (они не содержат магии и могут приходить как <=64 байт)
            # Дефрамер: ищем магию 0xA55A (LE: 5A A5), затем ждём весь кадр
            while True:
                if len(buf) < HDR_SIZE:
                    break
                if not (buf[0] == 0x5A and buf[1] == 0xA5):
                    idx = buf.find(MAGIC_LE)
                    if idx == -1:
                        # оставим хвост до 1 байта возможной магии
                        del buf[:max(0, len(buf)-1)]
                        break
                    else:
                        del buf[:idx]
                        if len(buf) < HDR_SIZE:
                            break
                hdr_bytes = bytes(buf[:HDR_SIZE])
                try:
                    (magic,ver,flags,seq,timestamp,total_samples,zone_count,zone1_offset,zone1_length,reserved,reserved2,crc16v)= struct.unpack('<H B B I I H H I I I H H', hdr_bytes)
                except struct.error:
                    # недостаточно данных для заголовка — ждём
                    break
                if magic != MAGIC:
                    # сдвинемся на байт вперёд и поищем магию снова
                    self.magic_bad += 1
                    del buf[0]
                    continue
                payload_len = int(total_samples)*2
                frame_total = HDR_SIZE + payload_len
                if len(buf) < frame_total:
                    # ждём остаток кадра
                    break
                payload = bytes(buf[HDR_SIZE:frame_total])
                # CRC опционален: при несовпадении не отбрасываем кадр, только считаем ошибку
                if flags & VF_CRC:
                    try:
                        calc = crc16_ccitt_false(hdr_bytes[:-2])
                        calc = crc16_ccitt_false(payload, calc)
                        if calc != crc16v:
                            self.crc_bad += 1
                    except Exception:
                        # если что-то пошло не так при расчёте CRC — не мешаем потоку
                        self.crc_bad += 1
                # TEST-бит (0x80):
                # - если это «чистый» тестовый кадр (нет битов ADC0/ADC1) — по умолчанию пропускаем,
                #   а при test_as_data дублируем на A и B;
                # - если вместе с TEST выставлены биты канала (DIAG: 0x81/0x82) — считаем обычным A/B кадром.
                if (flags & 0x80) and (flags & (VF_ADC0 | VF_ADC1)) == 0:
                    self.test_seen += 1
                    if self.test_as_data:
                        try:
                            fA = Frame(seq, timestamp, 0, flags, total_samples, payload)
                            fB = Frame(seq, timestamp, 1, flags, total_samples, payload)
                            self.asm.push(fA)
                            self.asm.push(fB)
                            self.frames += 2
                            self.bytes += payload_len * 2
                            self._working_seen = True
                        except Exception:
                            pass
                    del buf[:frame_total]
                    continue
                if flags & VF_ADC0:
                    adc_id = 0
                elif flags & VF_ADC1:
                    adc_id = 1
                else:
                    # неизвестный флаг — отбрасываем кадр
                    del buf[:frame_total]
                    continue
                f = Frame(seq,timestamp,adc_id,flags,total_samples,payload)
                self.asm.push(f)
                self.frames += 1
                self.bytes += payload_len
                del buf[:frame_total]
                self._working_seen = True
            now=time.time()
            # Если видим только STAT и нет рабочих кадров — один раз пробуем fallback
            if (not self._working_seen) and (not self._fallback_done) and (now - self.connected_t > 1.6):
                self._do_fallback_start()
            if now - self.stat_t >=1.0:
                with self.lock:
                    fps=self.frames; bps=self.bytes
                    print(f"fps={fps} bytes={bps} crc_bad={self.crc_bad} magic_bad={self.magic_bad} stereo_ready={self.asm.q.qsize()}")
                    self.frames=0; self.bytes=0; self.stat_t=now
    def get_stereo(self, timeout=0.0):
        try:
            return self.asm.q.get(timeout=timeout)
        except queue.Empty:
            return None

    # --- helpers for GUI ---
    def get_port_path_info(self):
        """Вернуть информацию о топологии USB для uhubctl/sysfs.

        Возвращает dict: {
          'bus': int|None,
          'address': int|None,
          'port_numbers': [ints] | None,
          'port_path': '1-1.3.2' | None,
          'hub_loc': '1-1.3' | None,
          'hub_port': 2 | None,
          'vid': int,
          'pid': int,
        }
        """
        info = {
            'bus': None,
            'address': None,
            'port_numbers': None,
            'port_path': None,
            'hub_loc': None,
            'hub_port': None,
            'vid': getattr(self.dev, 'idVendor', None),
            'pid': getattr(self.dev, 'idProduct', None),
        }
        try:
            bus = getattr(self.dev, 'bus', None)
            addr = getattr(self.dev, 'address', None)
            ports = None
            # PyUSB may expose 'port_numbers' (list) or only 'port_number'
            try:
                ports = list(getattr(self.dev, 'port_numbers'))
            except Exception:
                p1 = getattr(self.dev, 'port_number', None)
                if p1:
                    ports = [int(p1)]
            info['bus'] = bus
            info['address'] = addr
            info['port_numbers'] = ports
            if bus and ports:
                port_path = f"{bus}-" + ".".join(str(x) for x in ports)
                info['port_path'] = port_path
                if len(ports) >= 1:
                    hub_loc = f"{bus}-" + ".".join(str(x) for x in ports[:-1]) if len(ports) > 1 else f"{bus}-"
                    hub_port = int(ports[-1])
                    # Корректируем hub_loc: для верхнего уровня оставим вида '1-1'
                    if hub_loc.endswith('-') and ports:
                        hub_loc = f"{bus}-{ports[0]}"
                    info['hub_loc'] = hub_loc
                    info['hub_port'] = hub_port
        except Exception:
            pass
        return info

def watch_loop(interval=1.0):
    last_state = None
    us = None
    last_msg = 0
    while True:
        try:
            if us is None:
                dev_present = usb.core.find(idVendor=VID, idProduct=PID) is not None
                if dev_present:
                    try:
                        us = USBStream(profile=1, full=True, vid=VID, pid=PID, interactive=False)
                        print('[state] STREAMING start')
                    except Exception as e:
                        us = None
                        if time.time() - last_msg > 2:
                            print(f"[wait] found device but open failed: {e}")
                            last_msg = time.time()
                else:
                    if time.time() - last_msg > 2:
                        print(f"[wait] нет устройства {hex(VID)}:{hex(PID)}")
                        last_msg = time.time()
                    time.sleep(interval)
            else:
                if us.disconnected:
                    print('[state] LOST device, returning to wait')
                    try:
                        us.close()
                    except Exception:
                        pass
                    us = None
                    time.sleep(interval)
                else:
                    # poll for stereo pairs lightly (discard output here)
                    _ = us.get_stereo(timeout=0.01)
                    time.sleep(0.1)
        except KeyboardInterrupt:
            print('\n[exit]')
            if us:
                try:
                    us.close()
                except Exception:
                    pass
            break

if __name__=='__main__':
    if '--watch' in sys.argv:
        watch_loop()
    else:
        us = USBStream(profile=1, full=True)
        try:
            while True:
                pair = us.get_stereo(timeout=0.1)
                if pair:
                    (a,b) = pair
                    print(f"stereo seq={a.seq} samplesA={a.samples} samplesB={b.samples}")
        except KeyboardInterrupt:
            pass
        finally:
            us.close()
