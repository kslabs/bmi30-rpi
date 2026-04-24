# Utilities

В этой папке собраны вспомогательные утилиты для миграции системы и проверки источника загрузки.

## Утилиты

### menu.sh

Назначение:
Открывает интерактивное меню утилит в терминале, чтобы запускать основные операции из одного места.

Пример запуска:
```bash
./utilities/menu.sh
```

### list_tools.sh

Назначение:
Показывает список основных утилит и готовых команд для типовых операций.

Пример запуска:
```bash
./utilities/list_tools.sh
```

### check_bootloader.sh

Назначение:
Показывает текущий `BOOT_ORDER` EEPROM и коротко объясняет, что он означает для USB/eMMC.

Пример запуска:
```bash
./utilities/check_bootloader.sh
```

### set_usb_boot_priority.sh

Назначение:
Меняет только `BOOT_ORDER` в EEPROM, чтобы приоритет загрузки был у USB, даже если система сейчас запущена с внутренней флешки.

Что делает:
1. Показывает, с какого носителя сейчас работает root.
2. Читает текущий `BOOT_ORDER`.
3. Выставляет `BOOT_ORDER=0xf2614`, то есть режим USB-first.
4. Не трогает разделы, данные и файловую систему на eMMC/USB.

Когда использовать:
Если на устройстве уже стоит система на внутреннем накопителе, но нужно, чтобы после reboot Raspberry Pi сначала пытался грузиться с USB.

Пример запуска:
```bash
sudo ./utilities/set_usb_boot_priority.sh
```

### migrate_system_to_usb.sh

Назначение:
Копирует систему с eMMC на USB-диск файловым способом, а не побайтным клоном.

Что делает:
1. Определяет внутренний диск как источник, USB-диск как цель.
2. При необходимости пытается выставить USB-first в BOOT_ORDER EEPROM.
3. Переразбивает и форматирует USB.
4. Копирует boot и root через rsync с прогрессом.
5. Правит cmdline.txt и fstab на USB под новые PARTUUID.
6. Настраивает XRDP на один общий рабочий стол `:0` через `bmi30-x11vnc`.

Пример запуска:
```bash
sudo ./utilities/migrate_system_to_usb.sh --yes
```

### migrate_system_to_emmc.sh

Назначение:
Копирует систему с USB-диска на eMMC.

Что делает:
1. Определяет USB как источник, eMMC как цель.
2. Переразбивает и форматирует eMMC.
3. Копирует boot и root через rsync с прогрессом.
4. Правит cmdline.txt и fstab на eMMC под новые PARTUUID.
5. Настраивает XRDP на один общий рабочий стол `:0` через `bmi30-x11vnc`.

Пример запуска:
```bash
sudo ./utilities/migrate_system_to_emmc.sh --yes
```

Важно:
Этот скрипт нужно запускать из системы, загруженной не с eMMC, иначе цель будет занята текущим root.

### migrate_system_between_disks.sh

Назначение:
Общий движок миграции между ролями internal и usb.

Поддерживает режимы:
1. Полное копирование с переразметкой цели.
2. `--sync-only` для синхронизации только изменений без переразметки.

Когда нужен:
Используйте его только если нужен прямой вызов с явным указанием ролей или для отладки.

Пример запуска:
```bash
sudo ./utilities/migrate_system_between_disks.sh --source-role internal --target-role usb --yes
```

### sync_system_to_usb.sh

Назначение:
Синхронизирует изменения с eMMC на USB без переразметки целевого диска.

Пример запуска:
```bash
sudo ./utilities/sync_system_to_usb.sh --yes
```

### sync_system_to_emmc.sh

Назначение:
Синхронизирует изменения с USB на eMMC без переразметки целевого диска.

Пример запуска:
```bash
sudo ./utilities/sync_system_to_emmc.sh --yes
```

### check_boot_source.sh

Назначение:
Показывает, с какого носителя сейчас загружена система, и какие root/boot-разделы активны.

Что выводит:
1. Активный root-раздел.
2. Активный boot-раздел, если он смонтирован.
3. Тип носителя: eMMC/internal или USB.
4. UUID и PARTUUID активных разделов.

Пример запуска:
```bash
./utilities/check_boot_source.sh
```

### refresh_network_identity.sh

Назначение:
Обновляет hostname и связанные сетевые имена по аппаратному серийному номеру Raspberry Pi.

Что делает:
1. Строит имя вида `BMI30-XXXXXXXXX` по серийному номеру платы.
2. Обновляет hostname, `/etc/hosts`, hotspot, Avahi/mDNS, Samba и другие сетевые идентификаторы.
3. Используется при миграции, чтобы клоны на разных платах автоматически расходились по именам.

Пример запуска:
```bash
sudo ./utilities/refresh_network_identity.sh
sudo ./utilities/refresh_network_identity.sh --install-service
```

### setup_ethernet_portal.sh

Назначение:
Настраивает прямое подключение ПК к Raspberry Pi по Ethernet как локальный portal mode.

Что делает:
1. Назначает eth0 фиксированный адрес 10.43.0.1/24 через NetworkManager.
2. Поднимает локальный dnsmasq на eth0 и раздает IP по DHCP.
3. Перенаправляет все DNS-запросы клиентов на локальный IP Raspberry Pi.
4. Запускает web-страницу BMI30, чтобы компьютер после подключения открывал портал устройства.

Когда использовать:
Если нужно подключить ноутбук или ПК напрямую Ethernet-кабелем к BMI30/Raspberry Pi без внешнего роутера.

Важно:
Этот режим рассчитан именно на прямое подключение по кабелю.
Если включить его и воткнуть eth0 в существующую офисную LAN, Raspberry Pi начнет раздавать там свой DHCP.

Примеры запуска:
```bash
sudo ./utilities/setup_ethernet_portal.sh install
./utilities/setup_ethernet_portal.sh status
sudo ./utilities/setup_ethernet_portal.sh remove
```

### backup_to_cloud.sh

Назначение:
Создает один архив проекта с именем вида `YYYYMMDD_HHMMSS_XXXXXXXXX.tar.gz`,
где `XXXXXXXXX` автоматически берется из реального серийного номера Raspberry Pi.

Что делает:
1. Архивирует папку проекта (по умолчанию `~/Documents`) одним `.tar.gz` файлом.
2. Исключает тяжелые и восстанавливаемые части (`.git`, `.venv`, `.usbvenv`, кэши, старые локальные архивы).
3. По желанию выгружает архив в Google Drive через `rclone`.
4. Умеет поставить `systemd --user` таймер для автоматического ежедневного бэкапа в 23:00.
5. Поддерживает файл `utilities/backup_to_cloud.conf` для запуска из меню без ручного ввода параметров.
6. Не догоняет пропущенный бэкап после выключения: если устройство было выключено в 23:00, запуск просто пропускается.
7. Имя архива не зависит от текущего имени Wi-Fi и не запоминается от другого устройства.

Почему не весь `/home/techaid`:
1. В домашней папке много системного и временного, что не нужно для восстановления проекта.
2. Папка `Documents` уже содержит ваш рабочий проект и данные, а архив получается заметно меньше.

Примеры запуска:
```bash
# 1) Один раз создать конфиг (удобно для запуска из меню)
cp ./utilities/backup_to_cloud.conf.example ./utilities/backup_to_cloud.conf

# Разовый бэкап в облако
./utilities/backup_to_cloud.sh --remote gdrive: --drive-link "https://drive.google.com/drive/folders/1q7nYpi-rXyjx5XOgZ_G0rfQ2xyrLh-BC?usp=sharing"

# Установка ежедневного авто-бэкапа в 23:00
./utilities/backup_to_cloud.sh --install-timer --on-calendar "*-*-* 23:00:00"

# Проверить таймер
systemctl --user status bmi30-cloud-backup.timer
```

Важно:
Скрипт использует `rclone`, его нужно один раз настроить (`rclone config`) с remote `gdrive`.

### backup_status.sh

Назначение:
Показывает состояние таймера бэкапа, ближайший запуск и последние строки сервиса.

Пример запуска:
```bash
./utilities/backup_status.sh
```

## Рекомендуемый порядок работы

1. Подготовить USB:
```bash
sudo ./utilities/migrate_system_to_usb.sh --yes
```

2. Полностью выключить питание и включить CM5 с вставленным USB.

3. Проверить источник загрузки:
```bash
./utilities/check_boot_source.sh
```

4. Если нужно вернуть систему обратно на eMMC, загрузиться с USB и выполнить:
```bash
sudo ./utilities/migrate_system_to_emmc.sh --yes
```

Важно после копирования обратно на eMMC:
Режим USB-first подходит для сценария "если USB вставлен, грузимся с USB; если USB нет, грузимся с eMMC".
Поэтому возвращать BOOT_ORDER назад обычно не нужно.
Если требуется именно проверить запуск с eMMC, просто отключите USB-накопитель перед перезагрузкой.
