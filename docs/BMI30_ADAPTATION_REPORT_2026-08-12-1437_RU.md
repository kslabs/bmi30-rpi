# Отчёт адаптации BMI30 Raspberry — 2026-08-12-1437

## Результат

- Активный websplit-комплект: `2026-08-12-1437` (`Hub versions and connected groups`).
- BMI30 Agent: `0.2.2`.
- Hub check-in: `approved`, назначенный reverse SSH-порт `26395`.
- `bmi30-agent.service`: active/enabled.
- `bmi30-tunnel.service`: active/enabled; при установке агента не перезапускался.
- Компоненты BMI20 не изменялись и не останавливались.

## Безопасные поля check-in

```json
{
  "device_id": "BMI30-ABDD2DBC9775FBAE",
  "agent_version": "2026-08-12-1437",
  "firmware_version": "1.2.37",
  "connector_version": "0.2.2"
}
```

API token, private key и public key в отчёт не включены.

## Публичный `/api/status`

```json
{
  "raspberry_firmware_version": "2026-08-12-1437",
  "stm32_firmware_version": "1.2.37",
  "firmware_release": "2026-08-12-1437",
  "stm32_uid96": "333635343032511300090040"
}
```

Источник версии Raspberry: активный `bmi30_firmware_release.env` websplit-комплекта.

Источник версии STM32: реальное событие протокола `EVT1`, тип `0x00` (`fw_info`).
Текущий контроллер сообщил `fw_major=1`, `fw_minor=2`, `fw_patch=37`, то есть
`1.2.37`. UID96, версия signature и дата Raspberry-сборки не используются как
замена версии STM32. Если `EVT1 0x00` отсутствует или cache устарел, поле остаётся
пустой строкой.

## Подключённая группа

Публичный `/api/status` теперь содержит стабильные поля `groups` и
`groups_error`. Текущий источник — существующий STM32 USB/event-cache, второй
независимый источник состояния не создавался.

Текущий состав группы:

- `M10` — Master, online;
- `S03` — Slave, online;
- `S04` — Slave, online;
- `S07` — Slave, online, local.

Корневая локальная HTML-страница содержит серверную карточку `Connected Groups`
с ID/названием группы, ролью локального устройства, участниками, online/offline и
временем последнего соединения. При отсутствии связанных устройств отображается
`No connected groups`; ошибка cache передаётся отдельно и показывается как ошибка.

В event-cache также есть низкоуровневые диагностические данные: optic/DetADC/TX,
sensor bits, raw packet hex, event sequence, MCU ADC, USB/stream flags и UID96.
Они не добавлялись в публичную карточку: полезные optic/DetADC/TX/UID уже доступны
в авторизованной таблице `Group Devices` и `group_state`, а raw payload и внутренние
счётчики относятся к инженерной диагностике.

## Меню websplit-версий

Интерактивное меню показывает только полные комплекты текущего календарного
месяца. Вспомогательные пункты запуска, остановки, restart, status и массовой
SHA-проверки убраны из интерактивного списка; соответствующие CLI-команды и
systemd остаются доступны отдельно. Архивные комплекты не удалялись.

Переход между архитектурами также защищён от одновременного доступа к USB:

- выбор mono сначала останавливает `bmi30-core.service` и
  `bmi30-hotspot-info.service`, проверяет их остановку, завершает предыдущий
  mono-процесс и только затем запускает выбранный `BMI30.200.py`;
- выбор split-комплекта сначала штатно завершает запущенный mono-процесс и
  только затем активирует Core/Engine/GUI/Portal;
- при неподтверждённой остановке противоположной архитектуры запуск отменяется;
- `bmi30-agent.service` и `bmi30-tunnel.service` не затрагиваются.

## Проверки

- `py_compile`: PASS.
- `bash -n`: PASS.
- Основной unittest-набор: `73/73` PASS.
- Тесты BMI30 Agent: `11/11` PASS.
- Тесты безопасного перехода mono/split и сокращённого меню: `4/4` PASS.
- Bundle `2026-08-12-1437`: SHA256/manifest validation PASS.
- Прямой `http://127.0.0.1/api/status`: PASS.
- Прямая корневая HTML-страница: `Connected Groups`, `M10/S03/S04/S07` — PASS.
- Ручной check-in новым агентом: `approved` — PASS.
- Первый check-in `bmi30-agent.service` после установки: `approved` — PASS.
- Автоматическое открытие device-specific URL через Hub заблокировано политикой
  среды выполнения; URL не обходился. Требуется ручное открытие новой вкладки в Hub.

## Резервная копия и rollback

Резервная копия затронутых файлов и pre-change systemd/SHA-аудит:

`/home/techaid/Documents/backups/bmi30-adaptation-before-20260812_143029`

Rollback websplit:

```bash
cd /home/techaid/Documents
sudo ./switch_bmi30_split_versions.sh --activate 2026-08-12-1344
```

Rollback только BMI30 Agent:

```bash
sudo install -p -m 0755 \
  /home/techaid/Documents/backups/bmi30-adaptation-before-20260812_143029/system/opt/bmi30-agent/bmi30_agent.py \
  /opt/bmi30-agent/bmi30_agent.py
sudo systemctl restart bmi30-agent.service
```
