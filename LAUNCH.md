# BMI30 Vendor Bulk Oscilloscope — Инструкция Запуска

## Требования

### Python пакеты
```bash
pip install pyusb pyqtgraph PyQt5 numpy
# Или (если PyQt5 конфликтует):
pip install pyusb pyqtgraph PySide6 numpy
```

### USB Устройство
- **VID:PID**: `0xCAFE:0x4001`
- **Interface**: `IF#2`
- **Endpoints**: OUT 0x03, IN 0x83
- **Режим**: Vendor Bulk стерео (A/B пары, профили 1–2)

### Система
- **Linux** (или macOS/Windows с libusb)
- **Пользователь** должен иметь доступ к USB устройству (либо через `sudo`, либо через udev-правило)

---

## Запуск GUI Осциллографа

```bash
cd /home/techaid/Documents
python3 BMI30.200.py
```

### Что происходит при запуске

1. **Инициализация USB**:
   - Поиск устройства `0xCAFE:0x4001`
   - Переключение на IF#2
   - Установка alt=1 (Bulk endpoints active)
   - Синхронизация с устройством через EP0 GET_STATUS

2. **Handshake**:
   - Ожидание флагов: `alt1=1` и `out_armed=1` (из STAT v1)
   - Очистка HALT на EP0x03/0x83
   - Отправка команд: `SET_PROFILE`, `SET_FRAME_SAMPLES`, `START_STREAM`

3. **Потоковое воспроизведение**:
   - Ожидание A/B пар стерео-данных
   - Отображение на двух PyQtGraph графиках (ADC0, ADC1)
   - X-ось = индексы семплов (не время)
   - Y-ось = амплитуда (автомасштабирование)
   - Обновление ~200 FPS (при profile=1, full=True)

---

## Управление GUI

### Легенда (верхняя строка)
- **Левый край**: `BUF=XXX FREQ=200Hz` — размер буфера, частота
- **Выбор частоты**: Комбобокс `200 Hz` / `300 Hz`
- **Кнопка ↻**: Ручное переподключение к устройству
- **Кнопка ⚡**: Перезапит питания USB-порта (uhubctl, требует `sudo`)
- **Кнопка 🩺**: Диагностика EP0/STAT, SOFT_RESET/DEEP_RESET, проверка alt/out_armed

### График
- **Двойной клик** на кривой: показать/скрыть символы (точки)
- **Перетащить** по X/Y: панорамирование
- **Прокрутка мышью**: зумирование

### Завершение
- **Закрыть окно** или **Ctrl+C** в терминале

---

## Диагностика Проблем

### Проблема: "Устройство не найдено"

1. Проверьте подключение:
   ```bash
   lsusb | grep -i "cafe:4001"
   ```

2. Убедитесь в правах доступа:
   ```bash
   # Либо запустите с sudo:
   sudo python3 BMI30.200.py
   
   # Либо установите udev-правило (для непривилегированного доступа):
   sudo tee /etc/udev/rules.d/99-bmi30.rules << 'EOF'
   SUBSYSTEMS=="usb", ATTRS{idVendor}=="cafe", ATTRS{idProduct}=="4001", MODE="0666"
   EOF
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```

### Проблема: "No suitable interface with EP 0x83/0x3"

1. Устройство может быть в неправильном режиме (alt=0)
2. Нажмите кнопку **🩺** (диагностика), чтобы попытаться восстановить
3. Или перезапитайте устройство кнопкой **⚡** (требует `uhubctl`)

### Проблема: "EIO / Input/Output error"

1. Это означает, что EP0x03 был зазаблокирован (HALT)
2. GUI автоматически вызывает CLEAR_HALT после alt=1
3. Если ошибка повторяется — проверьте firmware на устройстве

### Проблема: "Нет данных на графике"

1. Нажмите кнопку **🩺** для диагностики состояния
2. Проверьте консоль (терминал) на предмет ошибок: `[diag]`, `[stream]`, `[err]`
3. Убедитесь, что устройство находится в режиме `alt=1` и `out_armed=1`
4. Проверьте, что `profile` установлен на 1 (можно изменить в коде)

### Проблема: "Частые переподключения"

1. Это может быть вызвано нестабильностью USB
2. Проверьте кабель и порт USB
3. Попробуйте другой USB-порт
4. Снизьте `profile` с 1 на 0 (медленнее, но стабильнее)

---

## Конфигурация

### Файл: `BMI30.200.py` (строки ~105–110)
```python
BMI30_PROFILE = 1  # 0=slow, 1=fast
BMI30_FULL_MODE = True  # True=FULL_MODE (все семплы), False=DIAG_MODE (ограниченно)
BMI30_Y_AUTO = 0  # 0=fixed Y-range, 1=auto-scale Y
BMI30_Y_MIN = -32768
BMI30_Y_MAX = 32767
```

### Файл: `USB_config.json` (если существует)
```json
{
  "profile": 1,
  "freq": 200,
  "frame_samples": 32
}
```

---

## Режимы Профиля (DevProfile)

| Profile | Mode | Rate (Hz) | Samples/Sec | Frame Size |
|---------|------|-----------|------------|------------|
| 0 | DIAG | 200 | ~1360 | 680B |
| 1 | FULL | 200 | ~1360 | 680B |
| 2 | FULL | 300 | ~912 | 456B |

---

## Структура STAT v1 (EP0 GET_STATUS ответ, 64 байта)

```
Byte Offset | Field Name     | Type  | Описание
0–4         | sig            | [u8]  | "STAT"
4           | version        | u8    | 1 (STAT v1)
5           | reserved0      | u8    | 0
6–8         | cur_samples    | u16LE | Текущий номер семпла в буфере
8–10        | frame_bytes    | u16LE | Размер одного фрейма в байтах
10–12       | test_frames    | u16LE | Количество тестовых фреймов
12–16       | produced_seq   | u32LE | Номер продуцированного фрейма
16–20       | sent0          | u32LE | Отправлено фреймов из очереди 0
20–24       | sent1          | u32LE | Отправлено фреймов из очереди 1
24–28       | dbg_tx_cplt    | u32LE | DMA завершений
28–32       | dbg_partial_frame_abort | u32LE | Отмен неполных фреймов
32–36       | dbg_size_mismatch | u32LE | Несоответствий размера
36–40       | dma_done0      | u32LE | DMA done счётчик 0
40–44       | dma_done1      | u32LE | DMA done счётчик 1
44–48       | frame_wr_seq   | u32LE | Номер записываемого фрейма
48–50       | flags_runtime  | u16LE | Bit2=hang_latched, остальные резерв
50–52       | flags2         | u16LE | Bit15=alt1, Bits[14:0]=service
52          | sending_ch     | u8    | 0=A, 1=B, 0xFF=idle
53          | reserved2      | u8    | Bit7=out_armed, Bits[1:0]=deep_reset_count_mod4
54–56       | pair_idx       | u16LE | Индекс текущей пары
56–58       | last_tx_len    | u16LE | Размер последней передачи
58–62       | cur_stream_seq | u32LE | Текущий номер потока
62–64       | reserved3      | u16LE | Резервировано
```

### Ключевые флаги для handshake

- **alt1**: `(flags2[50:52] >> 15) & 1` — устройство готово к alt=1
- **out_armed**: `(reserved2[53] >> 7) & 1` — устройство готово получать OUT команды

---

## Формат A/B Пары Стерео

Каждая пара состоит из двух фреймов (A и B) по **680 байт** (profile=1):

```
Frame Header (4 байта):
  Byte 0: 0xAA (маркер начала)
  Byte 1: Seq (0–255, циклический)
  Byte 2: Type (0x00=TYPE_A, 0x01=TYPE_B)
  Byte 3: Reserved

Данные (676 байт):
  338 семплов × 2 байта на семпл (int16LE)
```

### Синхронизация A/B

- Каждый тип (A и B) имеет собственный счётчик последовательности
- Устройство отправляет A, затем B, затем повторяет
- Tolerance: ±5 фреймов на отставание (для асинхронных очередей DMA)

---

## Примеры Диагностики (консоль)

### Успешный запуск
```
[init] ← detected device 0xCAFE:0x4001
[init] → IF#2 claimed, alt=0
[init] → alt=1 set via SET_INTERFACE
[wait] ← alt1=1, out_armed=1 (STAT ready)
[clear] → HALT cleared on 0x03/0x83
[tx] cmd=0x14 n=3  ← SET_PROFILE OK
[tx] cmd=0x20 n=1  ← START_STREAM OK
[stream] ← A[seq=1] (680B), B[seq=1] (680B), pairs=1, FPS=200
```

### EIO и восстановление
```
[tx-err] cmd=0x20 try=1 err=USBError(-1, 'error sending control message: Input/output error')
[tx-diag] alt1=1, out_armed=1 → CLEAR_HALT + retry
[clear] → HALT cleared on 0x03/0x83
[wait] ← alt1=1, out_armed=1 (ready after CLEAR_HALT)
[tx] cmd=0x20 n=1  ← START_STREAM OK (retry succeeded)
```

---

## Требования к Firmware Устройства

- **Interface IF#2** с Bulk Endpoints (OUT 0x03, IN 0x83)
- **STAT v1** формат на EP0 GET_STATUS (64 байта, sig="STAT", ver=1)
- **А/B паирование** с независимыми счётчиками последовательности
- **SET_INTERFACE (0x0B/0x01)** как основной метод alt-switching
- **Vendor SET_ALT (0x31)** как fallback (для legacy устройств)
- **OUT_ARMED флаг** в reserved2[53] bit7, автоматически возвращается после alt=1

---

## Быстрые Команды

### Полный перезапуск устройства
```bash
# Перезапитать USB-порт (требует sudo и uhubctl)
sudo uhubctl -l 1-1 -p 3 -a cycle
sleep 2
python3 BMI30.200.py
```

### Отладка транспорта
```bash
# Запустить smoke-тест (если устройство подключено)
python3 << 'PY'
from usb_vendor.usb_stream import USBStream
stream = USBStream(profile=1, full=True)
for i in range(10):
    pairs = stream.get_stereo(timeout=0.1)
    if pairs:
        print(f"Pair {i}: {len(pairs)} frames, seq_a={stream.seq_a}, seq_b={stream.seq_b}")
stream.close()
PY
```

### Проверка USB устройства
```bash
# Список всех USB устройств
lsusb

# Детали нашего устройства
lsusb -d cafe:4001 -v

# Мониторинг USB трафика (требует usbmon)
sudo modprobe usbmon
sudo chown $USER /dev/usbmon*
wireshark -i usbmon0 &  # или tcpdump -i usbmon0
```

---

## Файлы Проекта

- **BMI30.200.py** — Основной GUI (PyQtGraph + Qt)
- **usb_vendor/usb_stream.py** — USB транспорт, handshake, A/B сборка
- **USB_config.json** — Конфигурация (профиль, частота)
- **plot_config.json** — Конфигурация графика (цвета, масштаб)
- **History/** — Архив предыдущих версий
- **Cline/MCP/** — Model Context Protocol интеграции

---

## Лицензия и Благодарности

Проект разработан для BMI30 Vendor Bulk Stereo эмиттера.
Спецификация STAT v1 предоставлена производителем firmware.

---

**Последнее обновление**: 2025 (session with STAT v1 spec validation)
