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
CMD_ASYNC         = 0x18  # 0=strict pairs A/B, 1=independent A/B
CMD_SET_WINDOWS    = 0x10  # payload: <HHHH> start0,len0,start1,len1
CMD_SET_STREAM_MODE = 0x1A  # payload: <B> 0=LATEST(600), 1=LOSSLESS_ROI(200)
# Device-side DC adaptation toggle (firmware-dependent). Override via env if needed.
try:
    CMD_SET_DC_ADAPT = int(os.getenv("BMI30_CMD_SET_DC_ADAPT", "0x1B"), 0)
except Exception:
    CMD_SET_DC_ADAPT = 0x1B
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
    __slots__=("seq","timestamp","adc_id","flags","samples","payload","reserved","reserved2","ver")
    def __init__(self,seq,timestamp,adc_id,flags,samples,payload,reserved=0,reserved2=0,ver=0):
        self.seq=seq; self.timestamp=timestamp; self.adc_id=adc_id; self.flags=flags; self.samples=samples; self.payload=payload
        self.reserved = reserved
        self.reserved2 = reserved2
        self.ver = ver

class StereoAssembler:
    def __init__(self, relaxed: bool | None = None, relaxed_order: bool | None = None, ts_pairing: bool | None = None, ts_tol: float | None = None, independent: bool | None = None):
        self.bufA = {}
        self.bufB = {}
        # Очереди по умолчанию были маленькие (256) и при переполнении silently-drop'али пары.
        # Это может выглядеть как GAP на хосте даже при идеальном USB. Делаем размер настраиваемым и считаем потери.
        def _int_env(name: str, dflt: int) -> int:
            try:
                v = int(os.getenv(name, str(dflt)))
                return max(1, v)
            except Exception:
                return dflt
        self.q = queue.Queue(maxsize=_int_env('BMI30_ASM_Q_MAX', 2048))
        self.drop_pairs = 0
        self.drop_a = 0
        self.drop_b = 0
        # Relaxed mode: allow pairing with seq+1/seq-1 if exact seq not present
        # If param is None, respect environment variables (backwards compatibility)
        try:
            if relaxed is None:
                self.relaxed = str(os.getenv('BMI30_RELAXED_PAIRING', '1')).lower() not in ('0', 'false', 'no')
            else:
                self.relaxed = bool(relaxed)
        except Exception:
            self.relaxed = True
        # Дополнительный сверх-терпимый режим: если строгая состыковка по seq не найдена,
        # будем собирать пары по порядку прихода (первый A с первым B), игнорируя seq.
        # Это полезно, если прошивка использует независимый счётчик seq для каналов.
        try:
            if relaxed_order is None:
                self.relaxed_order = str(os.getenv('BMI30_RELAXED_ORDER', '1')).lower() not in ('0', 'false', 'no')
            else:
                self.relaxed_order = bool(relaxed_order)
        except Exception:
            self.relaxed_order = True
        # Timestamp-based pairing fallback: if exact seq matching fails, try pairing A/B by closeness of timestamps
        try:
            if ts_pairing is None:
                self.ts_pairing = str(os.getenv('BMI30_TS_PAIRING', '1')).lower() not in ('0', 'false', 'no')
            else:
                self.ts_pairing = bool(ts_pairing)
        except Exception:
            self.ts_pairing = True
        try:
            if ts_tol is None:
                # default tolerance in seconds (1ms)
                self.ts_tol = float(os.getenv('BMI30_TS_TOL', '0.001'))
            else:
                self.ts_tol = float(ts_tol)
        except Exception:
            self.ts_tol = 0.001
        self._ts_pair_count = 0
        self._seq_neighbor_pairs = 0
        # Independent channels mode: do not attempt to pair A/B, instead expose per-channel queues
        try:
            if independent is None:
                # Channels are independent by default — prefer not to auto-pair.
                self.independent = str(os.getenv('BMI30_INDEPENDENT_CHANNELS', '1')).lower() not in ('0', 'false', 'no')
            else:
                self.independent = bool(independent)
        except Exception:
            self.independent = False
        if self.independent:
            # queues for each channel (A=0,B=1)
            self.qA = queue.Queue(maxsize=_int_env('BMI30_ASM_QA_MAX', 2048))
            self.qB = queue.Queue(maxsize=_int_env('BMI30_ASM_QB_MAX', 2048))
    def _emit_pair(self, a: 'Frame', b: 'Frame'):
        try:
            self.q.put_nowait((a, b))
        except Exception:
            # queue.Full или другое: попробуем вытеснить один старый элемент и вставить новый
            try:
                self.drop_pairs += 1
                _ = self.q.get_nowait()
                self.q.put_nowait((a, b))
            except Exception:
                pass
    def _emit_frame_a(self, a: 'Frame'):
        try:
            self.qA.put_nowait(a)
        except Exception:
            try:
                self.drop_a += 1
                _ = self.qA.get_nowait()
                self.qA.put_nowait(a)
            except Exception:
                pass
    def _emit_frame_b(self, b: 'Frame'):
        try:
            self.qB.put_nowait(b)
        except Exception:
            try:
                self.drop_b += 1
                _ = self.qB.get_nowait()
                self.qB.put_nowait(b)
            except Exception:
                pass
    def push(self,f:Frame):
        # independent mode: just enqueue frames per-channel
        if self.independent:
            if f.adc_id == 0:
                self._emit_frame_a(f)
            else:
                self._emit_frame_b(f)
            # keep some minimal buffer cleanup
            if len(self.bufA) > 2048:
                self.bufA.clear()
            if len(self.bufB) > 2048:
                self.bufB.clear()
            return

        if f.adc_id==0:
            self.bufA[f.seq]=f
            if f.seq in self.bufB:
                a=self.bufA.pop(f.seq); b=self.bufB.pop(f.seq)
                self._emit_pair(a,b)
            elif ((f.seq-1) in self.bufB or (f.seq+1) in self.bufB) and (self.relaxed or self.ts_pairing):
                # allow neighbor seq pairing (seq-1 or seq+1) when relaxed or when ts close
                if (f.seq-1) in self.bufB:
                    candidate_key = f.seq-1
                else:
                    candidate_key = f.seq+1
                candidate = self.bufB.get(candidate_key)
                if candidate is not None and not self.relaxed:
                    # strict mode requires timestamp closeness
                    if getattr(candidate, 'timestamp', None) is not None and getattr(f, 'timestamp', None) is not None:
                        dt = abs((candidate.timestamp - f.timestamp) / 1_000_000.0)
                        if dt > self.ts_tol:
                            candidate = None
                if candidate is not None:
                    a = self.bufA.pop(f.seq)
                    b = self.bufB.pop(candidate_key)
                    self._emit_pair(a, b)
                    self._seq_neighbor_pairs += 1
                elif self.relaxed and (f.seq+1) in self.bufB:
                    # relaxed fallback: pair with seq+1 if present
                    a = self.bufA.pop(f.seq);
                    b = self.bufB.pop(f.seq+1)
                    self._emit_pair(a,b)
            elif self.relaxed_order and self.bufB:
                # Сверх-терпимый: возьмём ближайший по seq B (или просто первый) и спарим
                try:
                    # Найдём ключ B c минимальной разницей по seq
                    kb = min(self.bufB.keys(), key=lambda k: abs(int(k) - int(f.seq)))
                except Exception:
                    kb = next(iter(self.bufB.keys()))
                a=self.bufA.pop(f.seq)
                b=self.bufB.pop(kb)
                self._emit_pair(a,b)
            elif self.ts_pairing and self.bufB:
                # Last-resort: try to find B whose timestamp is close to this A
                try:
                    cand = None
                    best_dt = None
                    for k,bv in self.bufB.items():
                        if getattr(bv, 'timestamp', None) is None or getattr(f, 'timestamp', None) is None:
                            continue
                        dt = abs((bv.timestamp - f.timestamp) / 1_000_000.0)
                        if dt <= self.ts_tol and (best_dt is None or dt < best_dt):
                            cand = k; best_dt = dt
                    if cand is not None:
                        a = self.bufA.pop(f.seq)
                        b = self.bufB.pop(cand)
                        self._emit_pair(a,b)
                        self._ts_pair_count += 1
                        if self._ts_pair_count % 100 == 0:
                            try:
                                print(f"[ASM] timestamp-paired {self._ts_pair_count} times; last dt={best_dt:.6f}s", flush=True)
                            except Exception:
                                pass
                except Exception:
                    pass
        else:
            self.bufB[f.seq]=f
            if f.seq in self.bufA:
                a=self.bufA.pop(f.seq); b=self.bufB.pop(f.seq)
                self._emit_pair(a,b)
            elif ((f.seq-1) in self.bufA or (f.seq+1) in self.bufA) and (self.relaxed or self.ts_pairing):
                candidate_key = None
                if (f.seq-1) in self.bufA:
                    candidate_key = f.seq-1
                elif (f.seq+1) in self.bufA:
                    candidate_key = f.seq+1
                candidate = self.bufA.get(candidate_key)
                if candidate is not None and not self.relaxed:
                    if getattr(candidate,'timestamp',None) is not None and getattr(f,'timestamp',None) is not None:
                        dt = abs((candidate.timestamp - f.timestamp) / 1_000_000.0)
                        if dt > self.ts_tol:
                            candidate = None
                if candidate is not None:
                    a=self.bufA.pop(candidate_key); b=self.bufB.pop(f.seq)
                    self._emit_pair(a,b)
                    self._seq_neighbor_pairs += 1
                elif self.relaxed and (f.seq-1) in self.bufA:
                    a=self.bufA.pop(f.seq-1); b=self.bufB.pop(f.seq)
                    self._emit_pair(a,b)
            elif self.relaxed_order and self.bufA:
                try:
                    ka = min(self.bufA.keys(), key=lambda k: abs(int(k) - int(f.seq)))
                except Exception:
                    ka = next(iter(self.bufA.keys()))
                a=self.bufA.pop(ka)
                b=self.bufB.pop(f.seq)
                self._emit_pair(a,b)
            elif self.ts_pairing and self.bufA:
                # Last-resort: try to find A whose timestamp is close to this B
                try:
                    cand = None
                    best_dt = None
                    for k,av in self.bufA.items():
                        if getattr(av, 'timestamp', None) is None or getattr(f, 'timestamp', None) is None:
                            continue
                        dt = abs((av.timestamp - f.timestamp) / 1_000_000.0)
                        if dt <= self.ts_tol and (best_dt is None or dt < best_dt):
                            cand = k; best_dt = dt
                    if cand is not None:
                        a = self.bufA.pop(cand)
                        b = self.bufB.pop(f.seq)
                        self._emit_pair(a,b)
                        self._ts_pair_count += 1
                        if self._ts_pair_count % 100 == 0:
                            try:
                                print(f"[ASM] timestamp-paired {self._ts_pair_count} times; last dt={best_dt:.6f}s", flush=True)
                            except Exception:
                                pass
                except Exception:
                    pass
        # Простейшая защита от разрастания при редких несостыковках
        if len(self.bufA) > 2048:
            self.bufA.clear()
        if len(self.bufB) > 2048:
            self.bufB.clear()

class USBStream:
    def __init__(self, profile=1, full=True, vid=VID, pid=PID, interactive=False, allow_any=False, iface_prefer=None, test_as_data: bool=False, frame_samples: int | None = None, fast_mode: bool | None = None, assembler_relaxed: bool | None = None, assembler_relaxed_order: bool | None = None, assembler_ts_pairing: bool | None = None, assembler_ts_tol: float | None = None, assembler_independent: bool | None = None):
        self._running = True
        self.dev=None
        self.intf=None
        self.profile = profile
        self.full = full
        self.test_as_data = test_as_data
        self.frame_samples = frame_samples
        # Быстрый режим: жёстко задаём FULL/PROFILE/NS перед START и включаем keepalive/restart пороги
        try:
            fm_env = os.getenv('BMI30_FAST_MODE', None)
            fm_env_val = None if fm_env is None else (str(fm_env).lower() not in ('0','false','no'))
        except Exception:
            fm_env_val = None
        # По умолчанию быстрый режим ВКЛЮЧЕН (всегда рабочий режим)
        self.fast_mode = True if fast_mode is None and fm_env_val is None else bool(fast_mode if fast_mode is not None else fm_env_val)

        # Save assembler pairing overrides (None -> use env)
        self._asm_relaxed_override = assembler_relaxed
        self._asm_relaxed_order_override = assembler_relaxed_order
        self._asm_ts_pair_override = assembler_ts_pairing
        self._asm_ts_tol_override = assembler_ts_tol
        self._asm_independent_override = assembler_independent
        # Поведение можно ослабить через переменные окружения (уменьшаем «тряску» EP0/ALT/CDC у текущей прошивки)
        try:
            self.ignore_ready_flags = str(os.getenv('BMI30_IGNORE_ALT_READY','1')).lower() not in ('0','false','no')
        except Exception:
            self.ignore_ready_flags = True
        try:
            # По умолчанию разрешаем рестарт, чтобы удерживать поток длительно
            self.disable_restart = str(os.getenv('BMI30_DISABLE_RESTART','0')).lower() not in ('0','false','no')
        except Exception:
            self.disable_restart = False
        try:
            self.disable_cdc_kick = str(os.getenv('BMI30_DISABLE_CDC_KICK','1')).lower() not in ('0','false','no')
        except Exception:
            self.disable_cdc_kick = True
        # Пороги keepalive/restart (сек)
        def _float_env(name: str, dflt: float) -> float:
            try:
                return float(os.getenv(name, str(dflt)))
            except Exception:
                return dflt
        # Базовые значения (мягкие). В fast_mode делаем более агрессивные
        self.keepalive_sec = _float_env('BMI30_KEEPALIVE_SEC', 2.0)
        self.restart_after = _float_env('BMI30_RESTART_AFTER', 4.0)
        self.restart_min_interval = _float_env('BMI30_RESTART_MIN_INTERVAL', 3.0)
        if self.fast_mode:
            # Быстрый режим: чаще пингуем и быстрее рестартуем
            self.keepalive_sec = _float_env('BMI30_KEEPALIVE_SEC', 1.0)
            self.restart_after = _float_env('BMI30_RESTART_AFTER', 2.5)
            self.restart_min_interval = _float_env('BMI30_RESTART_MIN_INTERVAL', 2.0)
            self.disable_restart = False
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
            # По умолчанию НЕ делаем «чистый старт» (STOP/alt toggle), чтобы не мешать прошивке
            _disable_clean = str(os.getenv('BMI30_CLEAN_START','0')).lower() in ('0','false','no')
        except Exception:
            _disable_clean = True
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
        # Старт: отправим профиль/режим/окна/частоту/размер кадра (если заданы), затем START
        try:
            # Небольшая проверка готовности перед первыми bulk OUT
            try:
                self._wait_ready(timeout=1.0)
            except Exception:
                pass
            # Опционально сконфигурируем окна и частоту блока до старта (по умолчанию ВКЛ)
            try:
                # По умолчанию не шлём окна (как в простом рабочем читателе)
                send_windows = str(os.getenv('BMI30_SEND_WINDOWS','0')).lower() not in ('0','false','no')
            except Exception:
                send_windows = False
            if send_windows:
                try:
                    import struct as _st
                    # Значения по умолчанию совпадают с host скриптами: (100,300) и (700,300)
                    w0s = int(os.getenv('BMI30_WIN0_START', '100'))
                    w0l = int(os.getenv('BMI30_WIN0_LEN',   '300'))
                    w1s = int(os.getenv('BMI30_WIN1_START', '700'))
                    w1l = int(os.getenv('BMI30_WIN1_LEN',   '300'))
                    payload = _st.pack('<BHHHH', 0x10, w0s & 0xFFFF, w0l & 0xFFFF, w1s & 0xFFFF, w1l & 0xFFFF)
                    self.dev.write(EP_OUT, payload, timeout=1000)
                    # Небольшая пауза, чтобы устройство приняло конфиг
                    time.sleep(0.02)
                except Exception:
                    pass
            try:
                # По умолчанию не шлём частоту блока
                send_rate = str(os.getenv('BMI30_SEND_BLOCK_RATE','0')).lower() not in ('0','false','no')
            except Exception:
                send_rate = False
            if send_rate:
                try:
                    import struct as _st
                    # По умолчанию 200 Гц для профиля 1, 300 Гц для профиля 2
                    if 'BMI30_BLOCK_RATE' in os.environ:
                        rate_hz = int(os.getenv('BMI30_BLOCK_RATE','200'))
                    else:
                        rate_hz = 200 if int(self.profile or 1) == 1 else 300
                    payload = _st.pack('<BH', 0x11, rate_hz & 0xFFFF)
                    self.dev.write(EP_OUT, payload, timeout=1000)
                    time.sleep(0.02)
                except Exception:
                    pass
            try:
                send_profile = str(os.getenv('BMI30_SEND_PROFILE','0')).lower() not in ('0','false','no')
            except Exception:
                send_profile = False
            # Быстрый режим принудительно шлёт профиль и Ns до START
            if self.fast_mode:
                try:
                    prof = int(self.profile if self.profile is not None else 2)
                    self.send_cmd(CMD_SET_PROFILE, bytes([prof & 0xFF])); time.sleep(0.2 if prof == 1 else 0.01)
                except Exception:
                    pass
                try:
                    # SET_FULL_MODE(1/0)
                    self.send_cmd(CMD_SET_FULL_MODE, bytes([1 if self.full else 0])); time.sleep(0.05)
                except Exception:
                    pass
                # Важно: SET_FRAME_SAMPLES (0x17) нельзя слать для профиля 1 — ломает поток.
                # Для профиля 2 можно слать только если хост явно попросил (frame_samples!=None).
                if self.frame_samples is not None and int(self.profile or 2) == 2:
                    try:
                        ns = max(1, int(self.frame_samples)) & 0xFFFF
                        self.send_cmd(CMD_SET_FRAME_SAMPLES, ns.to_bytes(2, 'little'))
                        time.sleep(0.05)
                    except Exception:
                        pass
                # В fast-режиме дополнительно задаём частоту блока (200/300 Гц) перед START
                try:
                    rate_hz = 200 if int(self.profile or 1) == 1 else 300
                    self.set_block_rate(rate_hz)
                    time.sleep(0.05)
                except Exception:
                    pass
            elif send_profile:
                try:
                    if self.profile is not None:
                        self.send_cmd(CMD_SET_PROFILE, bytes([int(self.profile) & 0xFF])); time.sleep(0.02)
                except Exception:
                    pass
            try:
                self.send_cmd(CMD_SET_FULL_MODE, bytes([1 if self.full else 0])); time.sleep(0.02)
            except Exception:
                pass
            if self.frame_samples is not None and int(self.profile or 2) == 2:
                try:
                    # u16 LE (только для профиля 2; профиль 1 ломается при SET_FRAME_SAMPLES)
                    ns = max(1, int(self.frame_samples)) & 0xFFFF
                    self.send_cmd(CMD_SET_FRAME_SAMPLES, ns.to_bytes(2, 'little'))
                    time.sleep(0.02)
                except Exception:
                    pass
            # Профиль 1 требует больше времени на инициализацию
            delay = 0.3 if (int(self.profile if self.profile is not None else 2) == 1) else 0.05
            time.sleep(delay)
            self.send_cmd(CMD_START_STREAM, b"")
            time.sleep(0.05)
            # EP0 статус-пинг сразу после старта — выключен по умолчанию
            try:
                if str(os.getenv('BMI30_EP0_AFTER_START','0')).lower() not in ('0','false','no'):
                    self._get_status_ep0()
            except Exception:
                pass
        except Exception:
            pass
    # Консервативный старт: без дополнительных пинков/GET_STATUS (сделаем только по запросу)
        self.lock = threading.Lock()
        self.frames = 0; self.bytes = 0; self.crc_bad = 0; self.magic_bad = 0
        self.test_seen = 0
        self.last_stat = None
        # Track per-channel RX sequence continuity (adc_id=0/1).
        # This matches the user's definition of "no losses": each channel independently.
        self.seq_last_ch0: int | None = None
        self.seq_last_ch1: int | None = None
        self.seq_gap_ch0: int = 0
        self.seq_gap_ch1: int = 0
        self.seq_dup_ch0: int = 0
        self.seq_dup_ch1: int = 0
        self.seq_reset_ch0: int = 0
        self.seq_reset_ch1: int = 0
        # Per-channel timestamp continuity (u32 from header)
        self.ts_last_ch0: int | None = None
        self.ts_last_ch1: int | None = None
        self.ts_dup_ch0: int = 0
        self.ts_dup_ch1: int = 0
        self.ts_reset_ch0: int = 0
        self.ts_reset_ch1: int = 0
        # Timestamp delta histograms collected within each 1s stats interval
        self._ts_dhist_ch0: dict[int, int] = {}
        self._ts_dhist_ch1: dict[int, int] = {}
        self._ts_hist_lock = threading.Lock()

        # Seq delta histograms collected within each 1s stats interval.
        # Important: seq often increments by STEP=2 per-channel when A/B are interleaved.
        # We infer STEP from these histograms and estimate gaps based on it.
        self._seq_dhist_ch0: dict[int, int] = {}
        self._seq_dhist_ch1: dict[int, int] = {}

        # Warm-up: ignore early unstable intervals when switching modes.
        try:
            self.warmup_sec = float(os.getenv('BMI30_WARMUP_SEC', '5'))
        except Exception:
            self.warmup_sec = 5.0

        # Timestamp gap detection strictness.
        # We treat dt=2*step as jitter/batching by default and count gaps only for dt >= 3*step.
        # Override via env BMI30_TS_GAP_FACTOR (float).
        try:
            self.ts_gap_factor = float(os.getenv('BMI30_TS_GAP_FACTOR', '3'))
        except Exception:
            self.ts_gap_factor = 3.0
        self._stats_epoch = time.time()
        # Cumulative (post-warmup) totals for timestamp-based gaps/loss
        self._ts_gap_tot_ch0 = 0
        self._ts_gap_tot_ch1 = 0
        self._rx_tot_ch0 = 0
        self._rx_tot_ch1 = 0
        # Per-channel received frame counters (RX loop)
        self.rx_cnt_ch0: int = 0
        self.rx_cnt_ch1: int = 0
        # snapshots for per-second delta printing
        self._seq_gap_ch0_0: int = 0
        self._seq_gap_ch1_0: int = 0
        self._seq_dup_ch0_0: int = 0
        self._seq_dup_ch1_0: int = 0
        self._seq_reset_ch0_0: int = 0
        self._seq_reset_ch1_0: int = 0
        self._rx_cnt_ch0_0: int = 0
        self._rx_cnt_ch1_0: int = 0
        self._ts_dup_ch0_0: int = 0
        self._ts_dup_ch1_0: int = 0
        self._ts_reset_ch0_0: int = 0
        self._ts_reset_ch1_0: int = 0
        # allow overriding pairing policy via constructor params
        try:
            asm_relaxed = getattr(self, '_asm_relaxed_override', None)
            asm_relaxed_order = getattr(self, '_asm_relaxed_order_override', None)
            asm_ts_pair = getattr(self, '_asm_ts_pair_override', None)
            asm_ts_tol = getattr(self, '_asm_ts_tol_override', None)
            asm_indep = getattr(self, '_asm_independent_override', None)
        except Exception:
            asm_relaxed = asm_relaxed_order = asm_ts_pair = asm_ts_tol = asm_indep = None
        self.asm = StereoAssembler(relaxed=asm_relaxed, relaxed_order=asm_relaxed_order, ts_pairing=asm_ts_pair, ts_tol=asm_ts_tol, independent=asm_indep)
        try:
            print(f"[USBStream] StereoAssembler relaxed={self.asm.relaxed}, relaxed_order={self.asm.relaxed_order} independent={getattr(self.asm,'independent',False)}", flush=True)
        except Exception:
            pass
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
        # Флаг: один раз авто-исправить несоответствие профиля/частоты после старта
        self._rate_mismatch_fixed = False

    def set_block_rate(self, rate_hz: int):
        """Задать частоту блока (в Гц) через вендорский пакет 0x11."""
        try:
            import struct as _st
            payload = _st.pack('<BH', 0x11, int(rate_hz) & 0xFFFF)
            _ = self.dev.write(EP_OUT, payload, timeout=1000)
            try:
                print(f"[tx] set_block_rate {rate_hz}Hz")
            except Exception:
                pass
        except Exception as e:
            try:
                print('[tx] set_block_rate failed:', e)
            except Exception:
                pass

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
                    if self.ignore_ready_flags:
                        # Считаем готовым при получении STAT, не проверяя alt1/out_armed
                        ready = True
                        break
                    else:
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
        if getattr(self, 'disable_cdc_kick', False):
            return
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
        if not getattr(self, 'disable_cdc_kick', False):
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
    
    def set_buf_rate_fine(self, hz: int):
        """
        Установить частоту следования буферов.
        
        Args:
            hz: Целевая частота буферов (поддерживается 200-400 Гц)
            
        Raises:
            ValueError: Если частота вне допустимого диапазона
        """
        if not (200 <= hz <= 400):
            raise ValueError(f"Частота {hz} Гц вне диапазона 200-400 Гц")
        
        # CMD_SET_BUF_RATE_FINE = 0x1C
        # Формат: [cmd, rate_hz[7:0], rate_hz[15:8]]
        cmd = 0x1C
        payload = bytes([hz & 0xFF, (hz >> 8) & 0xFF])
        self.send_cmd(cmd, payload)
    
    def _rx_loop(self):
        buf = bytearray()
        MAGIC_LE = b"\x5A\xA5"
        while self._running and not self.disconnected:
            try:
                # Читаем умеренными порциями как в рабочих скриптах (2KB)
                data = bytes(self.dev.read(EP_IN, 2048, timeout=1000))
            except usb.core.USBError as e:
                if e.errno == 110: # timeout
                    # При длительном отсутствии рабочих кадров попробуем единоразовый fallback
                    now_t = time.time()
                    if (not self._working_seen) and (not self._fallback_done) and (now_t - self.connected_t > 1.6):
                        self._do_fallback_start()
                    # Keepalive/мягкий рестарт: если давно не было вообще RX
                    if (now_t - self.last_rx_t) > float(getattr(self, 'keepalive_sec', 2.0)) and (now_t - self.keepalive_last) > 0.9:
                        # EP0 keepalive, даже если bulk OUT залип
                        self._get_status_ep0()
                        self.keepalive_last = now_t
                    if (not getattr(self, 'disable_restart', False)) and (now_t - self.last_rx_t) > float(getattr(self, 'restart_after', 4.0)) and (now_t - self.last_restart_t) > float(getattr(self, 'restart_min_interval', 3.0)):
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
                            if self.frame_samples is not None and int(self.profile or 2) == 2:
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
                            fA = Frame(seq, timestamp, 0, flags, total_samples, payload, reserved=reserved, reserved2=reserved2, ver=ver)
                            fB = Frame(seq, timestamp, 1, flags, total_samples, payload, reserved=reserved, reserved2=reserved2, ver=ver)
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
                f = Frame(seq,timestamp,adc_id,flags,total_samples,payload,reserved=reserved,reserved2=reserved2,ver=ver)
                # Автопроверка: если хост явно задал frame_samples (и это профиль 2),
                # а устройство пошло с другим total_samples — один раз попробуем пере-применить конфиг.
                try:
                    if (not self._rate_mismatch_fixed) and self.frame_samples is not None and int(getattr(self, 'profile', 2) or 2) == 2:
                        exp = int(self.frame_samples)
                        if int(total_samples) != exp:
                            self._rate_mismatch_fixed = True
                            print(f"[verify] mismatch: expected {exp}, got {total_samples} → reapply config", flush=True)
                            try:
                                prof = int(getattr(self, 'profile', 2) or 2)
                                self.send_cmd(CMD_SET_PROFILE, bytes([prof & 0xFF])); time.sleep(0.01)
                            except Exception:
                                pass
                            try:
                                ns = max(1, exp) & 0xFFFF
                                self.send_cmd(CMD_SET_FRAME_SAMPLES, ns.to_bytes(2, 'little')); time.sleep(0.01)
                            except Exception:
                                pass
                            try:
                                rate = 200 if int(getattr(self, 'profile', 1) or 1) == 1 else 300
                                self.set_block_rate(rate); time.sleep(0.01)
                            except Exception:
                                pass
                            try:
                                self.send_cmd(CMD_START_STREAM, b""); time.sleep(0.02)
                            except Exception:
                                pass
                except Exception:
                    pass
                self.asm.push(f)
                self.frames += 1
                self.bytes += payload_len
                # Update per-channel seq continuity counters.
                try:
                    s = int(seq) & 0xFFFFFFFF
                    tsu = int(timestamp) & 0xFFFFFFFF
                    if int(adc_id) == 0:
                        self.rx_cnt_ch0 += 1
                        last = self.seq_last_ch0
                        if last is None:
                            self.seq_last_ch0 = s
                        else:
                            d = (s - int(last)) & 0xFFFFFFFF
                            if d == 0:
                                self.seq_dup_ch0 += 1
                            elif 0 < d < 0x80000000:
                                # Collect small deltas to infer nominal seq STEP (often 2).
                                if 0 < d <= 16:
                                    try:
                                        with self._ts_hist_lock:
                                            dhs = self._seq_dhist_ch0
                                            dhs[int(d)] = dhs.get(int(d), 0) + 1
                                    except Exception:
                                        pass
                                self.seq_last_ch0 = s
                            else:
                                self.seq_reset_ch0 += 1
                                self.seq_last_ch0 = s

                        # timestamp continuity for ch0
                        tlast = self.ts_last_ch0
                        if tlast is None:
                            self.ts_last_ch0 = tsu
                        else:
                            dt = (tsu - int(tlast)) & 0xFFFFFFFF
                            if dt == 0:
                                self.ts_dup_ch0 += 1
                            elif 0 < dt < 0x80000000:
                                # Record only reasonable deltas to infer nominal step (avoid huge outliers)
                                if 0 < dt <= 10_000_000:
                                    try:
                                        with self._ts_hist_lock:
                                            dh = self._ts_dhist_ch0
                                            dh[dt] = dh.get(dt, 0) + 1
                                    except Exception:
                                        pass
                                self.ts_last_ch0 = tsu
                            else:
                                self.ts_reset_ch0 += 1
                                self.ts_last_ch0 = tsu
                    else:
                        self.rx_cnt_ch1 += 1
                        last = self.seq_last_ch1
                        if last is None:
                            self.seq_last_ch1 = s
                        else:
                            d = (s - int(last)) & 0xFFFFFFFF
                            if d == 0:
                                self.seq_dup_ch1 += 1
                            elif 0 < d < 0x80000000:
                                # Collect small deltas to infer nominal seq STEP (often 2).
                                if 0 < d <= 16:
                                    try:
                                        with self._ts_hist_lock:
                                            dhs = self._seq_dhist_ch1
                                            dhs[int(d)] = dhs.get(int(d), 0) + 1
                                    except Exception:
                                        pass
                                self.seq_last_ch1 = s
                            else:
                                self.seq_reset_ch1 += 1
                                self.seq_last_ch1 = s

                        # timestamp continuity for ch1
                        tlast = self.ts_last_ch1
                        if tlast is None:
                            self.ts_last_ch1 = tsu
                        else:
                            dt = (tsu - int(tlast)) & 0xFFFFFFFF
                            if dt == 0:
                                self.ts_dup_ch1 += 1
                            elif 0 < dt < 0x80000000:
                                if 0 < dt <= 10_000_000:
                                    try:
                                        with self._ts_hist_lock:
                                            dh = self._ts_dhist_ch1
                                            dh[dt] = dh.get(dt, 0) + 1
                                    except Exception:
                                        pass
                                self.ts_last_ch1 = tsu
                            else:
                                self.ts_reset_ch1 += 1
                                self.ts_last_ch1 = tsu
                except Exception:
                    pass
                del buf[:frame_total]
                self._working_seen = True
            now=time.time()
            # Если видим только STAT и нет рабочих кадров — один раз пробуем fallback
            if (not self._working_seen) and (not self._fallback_done) and (now - self.connected_t > 1.6):
                self._do_fallback_start()
            if now - self.stat_t >= 1.0:
                with self.lock:
                    frames_n = self.frames
                    bytes_n = self.bytes
                    try:
                        dt_stat = float(now - float(self.stat_t))
                        if dt_stat <= 0:
                            dt_stat = 1.0
                    except Exception:
                        dt_stat = 1.0
                    try:
                        fps_hz = float(frames_n) / float(dt_stat)
                        bps_hz = float(bytes_n) / float(dt_stat)
                    except Exception:
                        fps_hz = float(frames_n)
                        bps_hz = float(bytes_n)
                    try:
                        # compute deltas since last stat tick
                        try:
                            dd0 = int(self.seq_dup_ch0) - int(getattr(self, '_seq_dup_ch0_0', 0))
                            dd1 = int(self.seq_dup_ch1) - int(getattr(self, '_seq_dup_ch1_0', 0))
                            dr0 = int(self.seq_reset_ch0) - int(getattr(self, '_seq_reset_ch0_0', 0))
                            dr1 = int(self.seq_reset_ch1) - int(getattr(self, '_seq_reset_ch1_0', 0))
                            rc0 = int(self.rx_cnt_ch0) - int(getattr(self, '_rx_cnt_ch0_0', 0))
                            rc1 = int(self.rx_cnt_ch1) - int(getattr(self, '_rx_cnt_ch1_0', 0))
                            td0 = int(self.ts_dup_ch0) - int(getattr(self, '_ts_dup_ch0_0', 0))
                            td1 = int(self.ts_dup_ch1) - int(getattr(self, '_ts_dup_ch1_0', 0))
                            tr0 = int(self.ts_reset_ch0) - int(getattr(self, '_ts_reset_ch0_0', 0))
                            tr1 = int(self.ts_reset_ch1) - int(getattr(self, '_ts_reset_ch1_0', 0))
                        except Exception:
                            dd0 = dd1 = dr0 = dr1 = rc0 = rc1 = 0
                            td0 = td1 = tr0 = tr1 = 0

                        # infer timestamp step and estimate timestamp-based gaps within this interval
                        def _mode_step(dh: dict[int, int]) -> int | None:
                            try:
                                if not dh:
                                    return None
                                return max(dh.items(), key=lambda kv: kv[1])[0]
                            except Exception:
                                return None

                        def _est_seq_gaps_from_step(dh: dict[int, int], step: int | None) -> int:
                            """Estimate missing frames based on observed seq deltas.

                            Handles STEP>1 (e.g. per-channel STEP=2 when A/B are interleaved).
                            """
                            try:
                                if not dh or not step or step <= 0:
                                    return 0
                                gaps = 0
                                for d, c in dh.items():
                                    if c <= 0 or d <= 0:
                                        continue
                                    if d <= step:
                                        continue
                                    missing = max(0, (int(d) // int(step)) - 1)
                                    # If delta is not an exact multiple of step, count at least one anomaly.
                                    if (int(d) % int(step)) != 0:
                                        missing = max(missing, 1)
                                    gaps += int(c) * int(missing)
                                return int(gaps)
                            except Exception:
                                return 0

                        def _est_gaps_from_step(dh: dict[int, int], step: int | None) -> int:
                            try:
                                if not dh or not step or step <= 0:
                                    return 0
                                gaps = 0
                                st = float(step)
                                try:
                                    factor = float(getattr(self, 'ts_gap_factor', 3.0))
                                except Exception:
                                    factor = 3.0
                                if not (factor > 1.0):
                                    factor = 2.0
                                for d, c in dh.items():
                                    if c <= 0 or d <= 0:
                                        continue
                                    dt = float(d)
                                    # Stricter rule: ignore small multiples (e.g., 2*step) as jitter/batching.
                                    if dt < (factor * st):
                                        continue
                                    # Estimate missing ticks conservatively using floor (avoid overcounting jitter).
                                    k_floor = int(dt // st)
                                    if k_floor <= 1:
                                        continue
                                    gaps += int(c) * int(max(0, k_floor - 1))
                                return int(gaps)
                            except Exception:
                                return 0

                        try:
                            with self._ts_hist_lock:
                                dh_ts0 = dict(getattr(self, '_ts_dhist_ch0', {}) or {})
                                dh_ts1 = dict(getattr(self, '_ts_dhist_ch1', {}) or {})
                                dh_seq0 = dict(getattr(self, '_seq_dhist_ch0', {}) or {})
                                dh_seq1 = dict(getattr(self, '_seq_dhist_ch1', {}) or {})
                                try:
                                    getattr(self, '_ts_dhist_ch0', {}).clear()
                                    getattr(self, '_ts_dhist_ch1', {}).clear()
                                    getattr(self, '_seq_dhist_ch0', {}).clear()
                                    getattr(self, '_seq_dhist_ch1', {}).clear()
                                except Exception:
                                    pass
                        except Exception:
                            dh_ts0 = {}
                            dh_ts1 = {}
                            dh_seq0 = {}
                            dh_seq1 = {}

                        ts_step0 = _mode_step(dh_ts0)
                        ts_step1 = _mode_step(dh_ts1)
                        ts_gap0 = _est_gaps_from_step(dh_ts0, ts_step0)
                        ts_gap1 = _est_gaps_from_step(dh_ts1, ts_step1)

                        # infer seq step and estimate seq-based gaps within this interval
                        seq_step0 = _mode_step(dh_seq0)
                        seq_step1 = _mode_step(dh_seq1)
                        dg0 = _est_seq_gaps_from_step(dh_seq0, seq_step0)
                        dg1 = _est_seq_gaps_from_step(dh_seq1, seq_step1)

                        # Maintain cumulative seq gap counters for compatibility with older consumers.
                        try:
                            self.seq_gap_ch0 += int(dg0)
                            self.seq_gap_ch1 += int(dg1)
                        except Exception:
                            pass

                        # compute per-channel loss percentage for this interval
                        try:
                            loss0 = (100.0 * float(dg0) / float(dg0 + rc0)) if (dg0 + rc0) > 0 else 0.0
                            loss1 = (100.0 * float(dg1) / float(dg1 + rc1)) if (dg1 + rc1) > 0 else 0.0
                        except Exception:
                            loss0 = loss1 = 0.0

                        try:
                            tsloss0 = (100.0 * float(ts_gap0) / float(ts_gap0 + rc0)) if (ts_gap0 + rc0) > 0 else 0.0
                            tsloss1 = (100.0 * float(ts_gap1) / float(ts_gap1 + rc1)) if (ts_gap1 + rc1) > 0 else 0.0
                        except Exception:
                            tsloss0 = tsloss1 = 0.0

                        # cumulative post-warmup
                        try:
                            warm = (now - float(getattr(self, '_stats_epoch', now))) < float(getattr(self, 'warmup_sec', 5.0))
                        except Exception:
                            warm = False
                        if not warm:
                            try:
                                self._ts_gap_tot_ch0 += int(ts_gap0)
                                self._ts_gap_tot_ch1 += int(ts_gap1)
                                self._rx_tot_ch0 += int(rc0)
                                self._rx_tot_ch1 += int(rc1)
                            except Exception:
                                pass
                        try:
                            tot0 = int(getattr(self, '_rx_tot_ch0', 0)) + int(getattr(self, '_ts_gap_tot_ch0', 0))
                            tot1 = int(getattr(self, '_rx_tot_ch1', 0)) + int(getattr(self, '_ts_gap_tot_ch1', 0))
                            tsloss0_tot = (100.0 * float(getattr(self, '_ts_gap_tot_ch0', 0)) / float(tot0)) if tot0 > 0 else 0.0
                            tsloss1_tot = (100.0 * float(getattr(self, '_ts_gap_tot_ch1', 0)) / float(tot1)) if tot1 > 0 else 0.0
                        except Exception:
                            tsloss0_tot = tsloss1_tot = 0.0

                        try:
                            rx0_hz = float(rc0) / float(dt_stat) if dt_stat > 0 else float(rc0)
                            rx1_hz = float(rc1) / float(dt_stat) if dt_stat > 0 else float(rc1)
                        except Exception:
                            rx0_hz = float(rc0)
                            rx1_hz = float(rc1)

                        if getattr(self.asm, 'independent', False):
                            qszA = self.asm.qA.qsize() if hasattr(self.asm, 'qA') else 0
                            qszB = self.asm.qB.qsize() if hasattr(self.asm, 'qB') else 0
                            # print(
                            #     f"dt={dt_stat:.3f}s frames={frames_n} fps={fps_hz:.1f}/s bytes={int(bps_hz)}B/s "
                            #     f"rxA={rx0_hz:.1f}/s rxB={rx1_hz:.1f}/s lossA={loss0:.1f}% lossB={loss1:.1f}% "
                            #     f"tsStepA={ts_step0} tsStepB={ts_step1} tsLossA={tsloss0:.1f}% tsLossB={tsloss1:.1f}% "
                            #     f"tsLossTotA={tsloss0_tot:.1f}% tsLossTotB={tsloss1_tot:.1f}% "
                            #     f"rxGapA+={dg0} rxGapB+={dg1} "
                            #     f"rxDupA+={dd0} rxDupB+={dd1} "
                            #     f"rxRstA+={dr0} rxRstB+={dr1} "
                            #     f"tsDupA+={td0} tsDupB+={td1} tsRstA+={tr0} tsRstB+={tr1} "
                            #     f"crc_bad={self.crc_bad} magic_bad={self.magic_bad} "
                            #     f"qA={qszA} qB={qszB} dropA={getattr(self.asm,'drop_a',0)} dropB={getattr(self.asm,'drop_b',0)}",
                            #     flush=True,
                            # )
                        else:
                            pass
                            # print(
                            #     f"dt={dt_stat:.3f}s frames={frames_n} fps={fps_hz:.1f}/s bytes={int(bps_hz)}B/s "
                            #     f"rxA={rx0_hz:.1f}/s rxB={rx1_hz:.1f}/s lossA={loss0:.1f}% lossB={loss1:.1f}% "
                            #     f"tsStepA={ts_step0} tsStepB={ts_step1} tsLossA={tsloss0:.1f}% tsLossB={tsloss1:.1f}% "
                            #     f"tsLossTotA={tsloss0_tot:.1f}% tsLossTotB={tsloss1_tot:.1f}% "
                            #     f"rxGapA+={dg0} rxGapB+={dg1} "
                            #     f"rxDupA+={dd0} rxDupB+={dd1} "
                            #     f"rxRstA+={dr0} rxRstB+={dr1} "
                            #     f"tsDupA+={td0} tsDupB+={td1} tsRstA+={tr0} tsRstB+={tr1} "
                            #     f"crc_bad={self.crc_bad} magic_bad={self.magic_bad} "
                            #     f"stereo_ready={self.asm.q.qsize()} dropPairs={getattr(self.asm,'drop_pairs',0)}",
                            #     flush=True,
                            # )
                    except Exception:
                        pass
                        # print(f"dt={dt_stat:.3f}s frames={frames_n} fps={fps_hz:.1f}/s bytes={int(bps_hz)}B/s crc_bad={self.crc_bad} magic_bad={self.magic_bad}")

                    # store snapshots for next tick
                    try:
                        self._seq_gap_ch0_0 = int(self.seq_gap_ch0)
                        self._seq_gap_ch1_0 = int(self.seq_gap_ch1)
                        self._seq_dup_ch0_0 = int(self.seq_dup_ch0)
                        self._seq_dup_ch1_0 = int(self.seq_dup_ch1)
                        self._seq_reset_ch0_0 = int(self.seq_reset_ch0)
                        self._seq_reset_ch1_0 = int(self.seq_reset_ch1)
                        self._rx_cnt_ch0_0 = int(self.rx_cnt_ch0)
                        self._rx_cnt_ch1_0 = int(self.rx_cnt_ch1)
                        self._ts_dup_ch0_0 = int(self.ts_dup_ch0)
                        self._ts_dup_ch1_0 = int(self.ts_dup_ch1)
                        self._ts_reset_ch0_0 = int(self.ts_reset_ch0)
                        self._ts_reset_ch1_0 = int(self.ts_reset_ch1)
                    except Exception:
                        pass
                    self.frames = 0; self.bytes = 0; self.stat_t = now
    def get_stereo(self, timeout=0.0):
        try:
            if getattr(self.asm, 'independent', False):
                # Independent mode: return a single frame ('A', frame) or ('B', frame).
                # IMPORTANT: do not starve channel B by always reading qA first.
                start = time.monotonic()
                try:
                    rr = int(getattr(self, '_indep_rr', 0))
                except Exception:
                    rr = 0
                # Toggle preference for next call.
                try:
                    self._indep_rr = 1 - rr
                except Exception:
                    pass

                def _remaining() -> float:
                    if timeout is None:
                        return 0.0
                    try:
                        t = float(timeout)
                    except Exception:
                        t = 0.0
                    if t <= 0:
                        return 0.0
                    rem = t - (time.monotonic() - start)
                    return rem if rem > 0 else 0.0

                first = ('A', getattr(self.asm, 'qA', None)) if rr == 0 else ('B', getattr(self.asm, 'qB', None))
                second = ('B', getattr(self.asm, 'qB', None)) if rr == 0 else ('A', getattr(self.asm, 'qA', None))
                # Fast path: check both queues without blocking first.
                # This avoids spending the whole timeout on an empty preferred queue
                # while data is already waiting in the other queue.
                for tag, q in (first, second):
                    if q is None:
                        continue
                    try:
                        item = q.get_nowait()
                        return (tag, item)
                    except queue.Empty:
                        continue

                # Slow path: wait in short slices and alternate both queues.
                # This keeps latency low and prevents artificial FPS cap (~1/timeout).
                rem = _remaining()
                if rem <= 0.0:
                    return None
                while rem > 0.0:
                    wait_slice = min(0.01, rem)
                    for tag, q in (first, second):
                        if q is None:
                            continue
                        try:
                            item = q.get(timeout=wait_slice)
                            return (tag, item)
                        except queue.Empty:
                            continue
                    rem = _remaining()
                return None
            else:
                return self.asm.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_frame(self, adc_id:int, timeout=0.0):
        """Return a single frame for adc_id (0 or 1) or None.

        adc_id can be 0 (A) or 1 (B).
        """
        try:
            if not getattr(self.asm, 'independent', False):
                return None
            if int(adc_id) == 0:
                return self.asm.qA.get(timeout=timeout)
            else:
                return self.asm.qB.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_buffer_depths(self) -> dict:
        """Return current queue/buffer depths for diagnostics.

        Returns dict with keys depending on assembler mode:
         - 'stereo_q' : number of paired A/B frames waiting
         - 'qA', 'qB' : per-channel queue sizes when independent
         - 'bufA', 'bufB' : number of unpaired frames buffered by assembler
        """
        try:
            depths = {}
            asm = getattr(self, 'asm', None)
            if asm is None:
                return {'stereo_q': 0}
            # paired queue
            try:
                depths['stereo_q'] = asm.q.qsize() if hasattr(asm, 'q') else 0
            except Exception:
                depths['stereo_q'] = 0
            # independent queues
            try:
                if getattr(asm, 'independent', False):
                    depths['qA'] = asm.qA.qsize() if hasattr(asm, 'qA') else 0
                    depths['qB'] = asm.qB.qsize() if hasattr(asm, 'qB') else 0
            except Exception:
                depths['qA'] = depths.get('qA', 0); depths['qB'] = depths.get('qB', 0)
            # internal assembler buffers awaiting pairing
            try:
                depths['bufA'] = len(getattr(asm, 'bufA', {}))
                depths['bufB'] = len(getattr(asm, 'bufB', {}))
            except Exception:
                depths['bufA'] = depths.get('bufA', 0); depths['bufB'] = depths.get('bufB', 0)
            return depths
        except Exception:
            return {'stereo_q': 0}

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
        # Demo: by default print compact stats once per second.
        # Use --print to also print individual frames (can be very noisy).
        print_frames = '--print' in sys.argv

        # Optional: switch streaming mode to match GUI behaviors.
        # --lossless-roi  : STOP → SET_WINDOWS(roi_start,roi_len,0,0) → SET_STREAM_MODE(1) → SET_ASYNC(0) → START
        # --latest        : STOP → SET_WINDOWS(0,0,0,0)     → SET_STREAM_MODE(0) → SET_ASYNC(1) → START
        want_lossless = ('--lossless-roi' in sys.argv) or ('--roi200' in sys.argv)
        want_latest = ('--latest' in sys.argv)
        force_async1 = ('--async1' in sys.argv)
        force_async0 = ('--async0' in sys.argv)

        # LOSSLESS_ROI window parameters
        roi_start = 280
        roi_len = 200
        # Demo connection parameters
        demo_profile = 1
        demo_frame_samples: int | None = None
        for a in list(sys.argv):
            if a.startswith('--profile='):
                try:
                    demo_profile = int(a.split('=', 1)[1])
                except Exception:
                    pass
            elif a.startswith('--frame-samples='):
                try:
                    demo_frame_samples = int(a.split('=', 1)[1])
                except Exception:
                    demo_frame_samples = None
            if a.startswith('--roi-len='):
                try:
                    roi_len = int(a.split('=', 1)[1])
                except Exception:
                    pass
            elif a.startswith('--roi-start='):
                try:
                    roi_start = int(a.split('=', 1)[1])
                except Exception:
                    pass
        try:
            roi_start = max(0, min(65535, int(roi_start)))
        except Exception:
            roi_start = 280
        try:
            roi_len = max(1, min(65535, int(roi_len)))
        except Exception:
            roi_len = 200

        # Optional: warm-up seconds for stats (ignore early unstable period after switching modes)
        warmup_sec = None
        for i, a in enumerate(list(sys.argv)):
            if a.startswith('--warmup='):
                try:
                    warmup_sec = float(a.split('=', 1)[1])
                except Exception:
                    warmup_sec = None
        if warmup_sec is not None:
            try:
                os.environ['BMI30_WARMUP_SEC'] = str(warmup_sec)
            except Exception:
                pass

        us = USBStream(profile=demo_profile, full=True, frame_samples=demo_frame_samples)
        try:
            if want_lossless or want_latest:
                import struct as _st
                try:
                    us.send_cmd(CMD_STOP_STREAM, b"")
                    time.sleep(0.05)
                except Exception:
                    pass

                if want_lossless:
                    us.send_cmd(CMD_SET_WINDOWS, _st.pack('<HHHH', int(roi_start) & 0xFFFF, int(roi_len) & 0xFFFF, 0, 0))
                    time.sleep(0.02)
                    us.send_cmd(CMD_SET_STREAM_MODE, b"\x01")
                    time.sleep(0.02)
                    # LOSSLESS_ROI default is strict pairs (0), but user may want independent channels (1)
                    async_mode = 0
                    if force_async1:
                        async_mode = 1
                    if force_async0:
                        async_mode = 0
                    us.send_cmd(CMD_ASYNC, bytes([async_mode]))
                    time.sleep(0.02)
                    us.send_cmd(CMD_START_STREAM, b"")
                    time.sleep(0.05)
                    print(f'[demo] LOSSLESS_ROI enabled: windows({roi_start},{roi_len},0,0) stream_mode=1 async={async_mode}', flush=True)
                else:
                    us.send_cmd(CMD_SET_WINDOWS, _st.pack('<HHHH', 0, 0, 0, 0))
                    time.sleep(0.02)
                    us.send_cmd(CMD_SET_STREAM_MODE, b"\x00")
                    time.sleep(0.02)
                    # LATEST default is independent (1), but allow forcing strict (0)
                    async_mode = 1
                    if force_async0:
                        async_mode = 0
                    if force_async1:
                        async_mode = 1
                    us.send_cmd(CMD_ASYNC, bytes([async_mode]))
                    time.sleep(0.02)
                    us.send_cmd(CMD_START_STREAM, b"")
                    time.sleep(0.05)
                    print(f'[demo] LATEST enabled: windows(0,0,0,0) stream_mode=0 async={async_mode}', flush=True)
        except Exception as e:
            try:
                print('[demo] mode switch failed:', e, flush=True)
            except Exception:
                pass

        last_t = time.time()
        cnt_a = 0
        cnt_b = 0
        last_seq_a = None
        last_seq_b = None
        last_seq_p = None
        step_a = None
        step_b = None
        step_p = None
        # Track delta distribution to infer step robustly (often STEP=2 when A/B are interleaved)
        delta_hist_a: dict[int, int] = {}
        delta_hist_b: dict[int, int] = {}
        delta_hist_p: dict[int, int] = {}
        crc0 = 0
        magic0 = 0
        dropa0 = 0
        dropb0 = 0
        dropp0 = 0
        samp_hist_a: dict[int, int] = {}
        samp_hist_b: dict[int, int] = {}
        pm_cnt = 0

        def _infer_step(delta_hist: dict[int, int]) -> int | None:
            try:
                if not delta_hist:
                    return None
                return max(delta_hist.items(), key=lambda kv: kv[1])[0]
            except Exception:
                return None

        def _estimate_gaps(delta_hist: dict[int, int], step: int | None) -> int:
            """Estimate missing frames in the interval based on observed seq deltas.

            This is computed at print-time to avoid artifacts when step inference changes.
            """
            try:
                if not delta_hist or not step or step <= 0:
                    return 0
                gaps = 0
                for d, c in delta_hist.items():
                    if d <= 0 or c <= 0:
                        continue
                    if d <= step:
                        continue
                    missing = max(0, (d // step) - 1)
                    # If delta is not an exact multiple of step, count at least one anomaly.
                    if (d % step) != 0:
                        missing = max(missing, 1)
                    gaps += int(c) * int(missing)
                return int(gaps)
            except Exception:
                return 0
        try:
            while True:
                got_any = False
                if getattr(us.asm, 'independent', False):
                    # Drain both channels so we don't artificially overflow qB.
                    a = us.get_frame(0, timeout=0.001)
                    if a is not None:
                        got_any = True
                        cnt_a += 1
                        try:
                            sa = int(getattr(a, 'samples', 0) or 0)
                            if sa > 0:
                                samp_hist_a[sa] = samp_hist_a.get(sa, 0) + 1
                        except Exception:
                            pass
                        if print_frames:
                            print(f"A seq={a.seq} samples={a.samples}")
                        if last_seq_a is not None:
                            d = int(a.seq) - int(last_seq_a)
                            if 0 < d <= 16:
                                delta_hist_a[d] = delta_hist_a.get(d, 0) + 1
                        last_seq_a = a.seq

                    b = us.get_frame(1, timeout=0.001)
                    if b is not None:
                        got_any = True
                        cnt_b += 1
                        try:
                            sb = int(getattr(b, 'samples', 0) or 0)
                            if sb > 0:
                                samp_hist_b[sb] = samp_hist_b.get(sb, 0) + 1
                        except Exception:
                            pass
                        if print_frames:
                            print(f"B seq={b.seq} samples={b.samples}")
                        if last_seq_b is not None:
                            d = int(b.seq) - int(last_seq_b)
                            if 0 < d <= 16:
                                delta_hist_b[d] = delta_hist_b.get(d, 0) + 1
                        last_seq_b = b.seq
                else:
                    pair = us.get_stereo(timeout=0.01)
                    if pair:
                        got_any = True
                        (a, b) = pair
                        cnt_a += 1
                        cnt_b += 1
                        try:
                            if int(getattr(a, 'seq', 0) or 0) != int(getattr(b, 'seq', 0) or 0):
                                pm_cnt += 1
                        except Exception:
                            pass
                        try:
                            sa = int(getattr(a, 'samples', 0) or 0)
                            sb = int(getattr(b, 'samples', 0) or 0)
                            if sa > 0:
                                samp_hist_a[sa] = samp_hist_a.get(sa, 0) + 1
                            if sb > 0:
                                samp_hist_b[sb] = samp_hist_b.get(sb, 0) + 1
                        except Exception:
                            pass
                        try:
                            # Use A's seq as pair seq reference
                            if last_seq_p is not None:
                                d = int(a.seq) - int(last_seq_p)
                                if 0 < d <= 16:
                                    delta_hist_p[d] = delta_hist_p.get(d, 0) + 1
                            last_seq_p = a.seq
                        except Exception:
                            pass
                        if print_frames:
                            print(f"stereo seq={a.seq} samplesA={a.samples} samplesB={b.samples}")

                if not got_any:
                    time.sleep(0.001)

                now = time.time()
                if now - last_t >= 1.0:
                    # Update inferred step as the most common observed delta (within last interval)
                    step_a = _infer_step(delta_hist_a)
                    step_b = _infer_step(delta_hist_b)
                    step_p = _infer_step(delta_hist_p)
                    gap_a = _estimate_gaps(delta_hist_a, step_a)
                    gap_b = _estimate_gaps(delta_hist_b, step_b)
                    gap_p = _estimate_gaps(delta_hist_p, step_p)
                    crc1 = getattr(us, 'crc_bad', 0)
                    magic1 = getattr(us, 'magic_bad', 0)
                    dropa1 = getattr(us.asm, 'drop_a', 0)
                    dropb1 = getattr(us.asm, 'drop_b', 0)
                    dropp1 = getattr(us.asm, 'drop_pairs', 0)
                    qszA = us.asm.qA.qsize() if getattr(us.asm, 'independent', False) and hasattr(us.asm, 'qA') else 0
                    qszB = us.asm.qB.qsize() if getattr(us.asm, 'independent', False) and hasattr(us.asm, 'qB') else 0
                    qszP = us.asm.q.qsize() if (not getattr(us.asm, 'independent', False)) and hasattr(us.asm, 'q') else 0

                    if getattr(us.asm, 'independent', False):
                        # Most-common sample count seen in the last second
                        try:
                            sa_mode = max(samp_hist_a.items(), key=lambda kv: kv[1])[0] if samp_hist_a else None
                            sb_mode = max(samp_hist_b.items(), key=lambda kv: kv[1])[0] if samp_hist_b else None
                        except Exception:
                            sa_mode = sb_mode = None
                        print(
                            f"A={cnt_a}/s B={cnt_b}/s stepA={step_a} stepB={step_b} "
                            f"gapA={gap_a} gapB={gap_b} "
                            f"samplesA~={sa_mode} samplesB~={sb_mode} "
                            f"crc+={crc1-crc0} magic+={magic1-magic0} "
                            f"qA={qszA} qB={qszB} dropA+={dropa1-dropa0} dropB+={dropb1-dropb0}",
                            flush=True,
                        )
                    else:
                        try:
                            sa_mode = max(samp_hist_a.items(), key=lambda kv: kv[1])[0] if samp_hist_a else None
                            sb_mode = max(samp_hist_b.items(), key=lambda kv: kv[1])[0] if samp_hist_b else None
                        except Exception:
                            sa_mode = sb_mode = None
                        print(
                            f"stereo={cnt_a}/s stepP={step_p} gapP={gap_p} pm={pm_cnt} "
                            f"crc+={crc1-crc0} magic+={magic1-magic0} "
                            f"samplesA~={sa_mode} samplesB~={sb_mode} "
                            f"qPairs={qszP} dropPairs+={dropp1-dropp0}",
                            flush=True,
                        )

                    cnt_a = 0
                    cnt_b = 0
                    delta_hist_a.clear()
                    delta_hist_b.clear()
                    delta_hist_p.clear()
                    samp_hist_a.clear()
                    samp_hist_b.clear()
                    pm_cnt = 0
                    crc0 = crc1
                    magic0 = magic1
                    dropa0 = dropa1
                    dropb0 = dropb1
                    dropp0 = dropp1
                    last_t = now
        except KeyboardInterrupt:
            pass
        finally:
            us.close()
