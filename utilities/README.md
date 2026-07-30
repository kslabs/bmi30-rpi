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

### create_bmi30_split_bundle.sh / switch_bmi30_split_versions.sh

Назначение:
Сохраняет и переключает BMI30 только полными совместимыми websplit-комплектами.

В один комплект входят active core и его engine, GUI, portal, project/system
`bmi30_config.json`, `bmi30_sel.json`, DC calibration, весь `usb_vendor` и
player recordings. Для всех файлов записывается `SHA256SUMS`.

Старые снимки, где сохранены только core/engine, остаются в `host/` как
история, но не показываются как доступные для переключения: совместимость их
общих GUI/portal/config/usb_stream подтвердить невозможно.

Создать полный комплект текущей активной версии:
```bash
sudo ./utilities/create_bmi30_split_bundle.sh \
  --id YYYY-MM-DD-HHMM-topic \
  --label "Короткое описание" \
  --origin "Источник и назначение"
```

Импортировать только активную версию проекта со смонтированного eMMC:
```bash
sudo ./utilities/create_bmi30_split_bundle.sh \
  --id YYYY-MM-DD-HHMM-emmc-runtime \
  --label "eMMC active runtime" \
  --origin "Импорт с eMMC" \
  --source-project /mnt/emmc-root/home/techaid/Documents \
  --source-system-root /mnt/emmc-root
```

Показать и проверить безопасный список:
```bash
./switch_bmi30_split_versions.sh --list
./switch_bmi30_split_versions.sh --validate
```

При выборе версия сначала проверяется по SHA-256 и компилируется в staging.
Затем целиком разворачивается в `host/bmi30_active_runtime`, устанавливается
соответствующая runtime-копия portal и BMI30 config, после чего одновременно
перезапускаются core и portal. При ошибке переключатель возвращает предыдущий
полный комплект.

`host/bmi30_active_runtime` и исторические комплекты в
`host/bmi30_split_bundles` являются локальными данными устройства и защищены от
удаления через `rsync --delete`. Обычный firmware release публикует только один
полный bundle, указанный в `host/bmi30_split_active_version.env`, проверяет его
`SHA256SUMS` и после копирования атомарно разворачивает в active runtime. При
облачной активации текущие локальные настройки целевого устройства сохраняются.

Для переноса полного локального списка и настроек на другой Raspberry Pi
используется отдельный recovery-архив:
```bash
./utilities/backup_bmi30_recovery_to_cloud.sh
```

Он загружается в облачный подкаталог `recovery/` вместе с SHA-256 и указателем
`bmi30_project_recovery_latest.env`. Общий firmware latest при этом не меняется.

Проверка скачанного архива:
```bash
./utilities/restore_bmi30_recovery_archive.sh \
  bmi30_project_recovery_YYYYMMDD_HHMMSS.tar.gz --verify-only
```

Восстановление проекта и сохранённого активного комплекта:
```bash
sudo ./utilities/restore_bmi30_recovery_archive.sh \
  bmi30_project_recovery_YYYYMMDD_HHMMSS.tar.gz \
  --apply --activate saved --yes
```

Recovery специально не содержит `.git`, venv, системные пакеты, device
identity, rclone credentials и `secrets/`; они на другом Raspberry Pi должны
быть установлены или настроены отдельно.

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

### backup_to_cloud.sh / cloud_sync_now.sh / update_from_cloud.sh

Назначение:
Доставляет одну общую прошивку BMI30 через общий Google Drive:
- на облаке хранится один актуальный firmware release для всех устройств;
- master/slave не имеют разных облачных версий проекта;
- публикация release выполняется явно, командой оператора;
- Portal примерно раз в час автоматически и низкоприоритетно читает только маленький cloud marker;
- скачивание и установка выполняются только после нажатия активной кнопки `Update` в шапке Portal;
- документация из `docs/`, а также файлы `*.md`, `*.txt`, `*.pdf` и `*.rst` обновляются вместе с прошивкой;
- локальная identity устройства, секреты, runtime-файлы, логи, записи и рабочие настройки GUI не входят в firmware release.

Что делает:
1. Архивирует firmware-содержимое и документацию проекта, включая активный `host/bmi30_split_active_version.env` и ровно один выбранный полный websplit bundle.
2. Исключает `.git`, `.codex`, venv, кэши, обычные и ротационные логи, `backups`, `.bmi30_cloud_sync`, `secrets`, локальный active runtime, временные stage/rollback, записи вне активного bundle, обучающие/калибровочные данные и локальные GUI runtime-файлы. Генерируемый `host/bmi30_split_active_version.env` передаётся устройствам, но не участвует в content-signature: изменение времени успешной активации не считается новой прошивкой.
3. Перед упаковкой создаёт `host/bmi30_firmware_release.env`: точное время release и SHA-256 активных core/engine/GUI/portal.
4. Называет общий архив `bmi30_backup_YYYYMMDD_HHMMSS.tar.gz` для совместимости со старыми updater; manifest однозначно помечает его как firmware release, серийный номер устройства в имя не входит.
5. Выгружает архив через `rclone` в Google Drive и обновляет указатель `bmi30_latest.env`.
6. Фоновая проверка Portal сравнивает датированные версии marker и текущего release. До появления строго более новой версии кнопки `Update` и `Rollback` неактивны.
7. При ручном обновлении отдельный systemd worker скачивает указанный архив, проверяет SHA-256, создаёт локальный `pre_update_*.tar.gz` и применяет проект через `rsync --delete`; этап и процент видны прямо на кнопке.
8. После применения сверяет active env и SHA-256 всех четырёх компонентов с release manifest, обновляет systemd units, устанавливает portal с сохранением времени файла и проверяет runtime-копию побайтно.
9. После успешного обновления Portal разрешает одношаговый `Rollback` к полному bundle, работавшему непосредственно перед обновлением; версия, label, notes и даты показываются в английской hover-подсказке.
10. Локально сохраняются только последние 5 firmware-архивов, 3 pre-update снимка и 2 скачанных incoming-архива.
11. Старый user systemd timer автоматической установки отключается при запуске Portal; timer публикации нужен только на устройстве, которое сознательно выпускает release.

Конфигурация:
```bash
cp utilities/backup_to_cloud.conf.example utilities/backup_to_cloud.conf
```

Одинаковый конфиг можно копировать на все устройства. Роль устройства задаётся только локальной identity вне firmware release.

Опубликовать текущую прошивку в облако:
```bash
./utilities/backup_to_cloud.sh --force
```

Создать локальный firmware release без выгрузки:
```bash
./utilities/backup_to_cloud.sh --local-only
```

Проверить и установить сегодняшнюю прошивку из облака:
```bash
./utilities/cloud_sync_now.sh --today-only
```

Принудительно переустановить последнюю прошивку из облака:
```bash
./utilities/update_from_cloud.sh --force
```

Отключить старый timer автоматической установки (команда совместимости):
```bash
./utilities/update_from_cloud.sh --install-timer
```

Автопубликация и автоустановка отключены. Готовый release публикуется вручную командой `./utilities/backup_to_cloud.sh --force`; установка на устройстве запускается кнопкой `Update` в Portal.

Проверка состояния:
```bash
./utilities/backup_status.sh
```

Важно:
Для облачной синхронизации нужен настроенный `rclone` remote, например `gdrive:`. Папка Google Drive задаётся через `REMOTE_FOLDER_ID`.

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
