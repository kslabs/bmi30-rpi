# BMI30: сохранение настроек, оптический затвор звука и фиксированная топология master/slave

Дата исследования: 2026-07-16

Статус: только исследование и проектирование. Код runtime, конфигурации, bundle, systemd-службы, прошивка STM32 и облачные данные не изменялись.

## 1. Область исследования

Исследовалась websplit-система BMI30, а не legacy-монолит.

Во время фактической проверки запущенный процесс core использовал комплект:

- bundle: `2026-07-15-0832`;
- core: `host/bmi30_active_runtime/project/host/BMI30.001.py.2026-07-15-0832`;
- engine: `host/bmi30_active_runtime/project/host/BMI30.200.py.2026-07-15-0832`;
- portal source/runtime: `host/bmi30_active_runtime/project/hotspot_info_server.py` и `/usr/local/bin/bmi30-hotspot-info-server.py`;
- активный env: `host/bmi30_split_active_version.env`.

В журнале версий при этом строка `2026-07-16-1250` была помечена как активная. Это отдельное несоответствие между журналом и фактическим `active env`; исследование ниже опирается на реально запущенный процесс и его API, а не на метку в CSV.

## 2. Краткий итог

Найдены три связанные архитектурные причины.

1. У настроек нет одного владельца и одного канонического файла. Portal, core и engine читают и записывают разные JSON-файлы. При переключении версии immutable bundle заново разворачивает старые снимки конфигурации, а текущие изменения обратно в состояние этой версии не сохраняются. Обычный cloud firmware archive эти локальные файлы намеренно исключает.

2. В активном engine оптический затвор звука реализован неполно. Он использует только локальный optic bit, разрешает звук при неизвестном/устаревшем состоянии, не проверяется в hold/repeat-пути и не восстанавливает сохранённую галочку после запуска. В архивном снимке `2026-07-13-1046-slave-master-optic-gate` уже есть более правильная role-aware fail-closed логика, но она отсутствует в активном engine.

3. После запуска нет постоянной host-конфигурации топологии. Firmware по умолчанию использует auto-role/UID arbitration, поэтому выбранный пользователем master не закреплён. Portal отправляет только live-запрос, не сохраняет назначение, а активный core не содержит обработчика `sync_mode`. Номер slave в firmware описан как временный и должен повторно задаваться host после каждого reset/reconnect.

## 3. Проблема 1: настройки теряются после перезапуска и переключения версии

### 3.1. Подтверждённое текущее устройство конфигурации

Одновременно существуют как минимум следующие копии настроек.

| Компонент | Фактически выбранный файл | Поведение |
|---|---|---|
| Установленный portal | `/etc/bmi30/portal_config.json` | Portal запущен без `User=` и первым выбирает этот файл. Формы Portal сохраняют сюда рабочие параметры. |
| Core service | `/usr/local/bin/host/bmi30_config.json` | Core запущен как `techaid`. Файл `/etc/bmi30/portal_config.json` имеет режим `0640` и другого владельца, поэтому core выбирает следующий читаемый кандидат. |
| Engine | `host/bmi30_active_runtime/project/host/bmi30_config.json` | Функции engine жёстко строят путь через `os.path.dirname(__file__)` и записывают JSON рядом с engine. Переменная `BMI30_CONFIG_JSON` ими не используется. |
| Immutable bundle | `host/bmi30_split_bundles/<id>/project/host/bmi30_config.json` | Начальный снимок проектной конфигурации версии. После создания bundle не обновляется. |
| Immutable bundle | `host/bmi30_split_bundles/<id>/system/etc/bmi30/portal_config.json` | Системный снимок настроек на момент создания bundle. |
| Immutable bundle | `host/bmi30_split_bundles/<id>/system/usr/local/bin/host/bmi30_config.json` | Снимок установленного fallback-файла на момент создания bundle. |
| Основной проект | `host/bmi30_config.json` | Ещё одна копия; часть portal-кода отдельно обновляет в ней LED patterns. |

Это не резервные зеркала одного состояния: файлы реально расходятся по значениям и времени обновления.

### 3.2. Наблюдавшиеся расхождения

Во время исследования были зафиксированы, в частности, такие разные значения:

- `avg_n`: установленный config содержал `40`, portal config содержал `24`, runtime config позднее содержал другое live-значение;
- Detection confirmations: установленный config — `4`, portal/runtime — `5`;
- Noise averaging window: установленный config — `10 s`, portal/runtime — `5 s`;
- `optic_reaction_enabled`: сохранённые проверенные файлы содержали `false`, а live API core сообщал `true`;
- значения порогов и автоматической адаптации также различались между `/etc`, `/usr/local/bin/host` и active runtime.

Значения могли меняться через UI во время работы, но сам факт одновременного расхождения подтверждает отсутствие единого источника истины.

### 3.3. Почему обычный restart восстанавливает не те значения

Последовательность сейчас приблизительно такая:

1. Пользователь сохраняет форму Portal.
2. Portal пишет значения в `/etc/bmi30/portal_config.json`.
3. Portal отправляет live API-команду core.
4. Часть обработчиков core/engine применяет значение только в памяти, часть записывает его в active-runtime JSON, часть записывает fallback config.
5. После restart core заново выбирает `/usr/local/bin/host/bmi30_config.json`, а engine сначала читает файл рядом с собой.
6. Core затем применяет свои defaults поверх части значений engine.

В результате live-настройка может работать до перезапуска, но следующий старт берёт другое, более старое значение.

Особенно показателен `optic_reaction_enabled`:

- active engine инициализирует его как `False`;
- Portal применяет галочку live-командой;
- active setter меняет только поле в памяти и ничего не сохраняет;
- startup core не загружает и не применяет эту настройку.

Поэтому эта галочка гарантированно может исчезнуть при restart core.

### 3.4. Почему переключение версии сбрасывает настройки

`switch_bmi30_split_versions.sh` при активации:

1. копирует `bundle/project/` в новый `host/bmi30_active_runtime/project/` через `rsync --delete`;
2. устанавливает сохранённый в bundle system config в `/etc/bmi30/portal_config.json`;
3. устанавливает сохранённый fallback config в `/usr/local/bin/host/bmi30_config.json`;
4. перезапускает core и portal.

Перед этим текущая конфигурация активной версии никуда не checkpoint-ится. При возврате к версии снова разворачивается первоначальный immutable-снимок bundle, а не последние пользовательские настройки этой версии.

Следовательно, текущий bundle является полным снимком только на момент его создания, но не является сохраняемой рабочей копией с изменяемым состоянием.

### 3.5. Почему cloud restore не гарантирует восстановление текущих настроек

Обычный firmware cloud archive намеренно исключает:

- `host/bmi30_active_runtime`;
- `host/bmi30_split_bundles`;
- `host/bmi30_config.json`;
- `host/bmi30_sel.json`;
- calibration/runtime data.

Поэтому текущие локальные настройки устройства не входят в обычную firmware-публикацию.

Recovery archive включает каталог `host/bmi30_split_bundles`, но исключает active runtime. Он восстанавливает сохранённые внутри bundle снимки, а не изменения, сделанные после активации bundle. Фактический `/etc/bmi30/portal_config.json` также находится вне каталога проекта и не попадает в recovery автоматически; он присутствует только в том виде, в каком ранее был скопирован внутрь конкретного bundle.

Итог: recovery восстанавливает исторические defaults bundle, но не обязательно последнее рабочее состояние каждой версии и каждого физического устройства.

### 3.6. Предлагаемая архитектура исправления

Нельзя продолжать синхронизировать несколько JSON-файлов best-effort. Нужны один владелец и явные области данных.

Рекомендуемое разделение:

1. **Version settings** — изменяемые рабочие параметры конкретного bundle на конкретном устройстве: detector, Automatic threshold, Noise averaging window, confirmations, DC timing, avg, sound, optic reaction, LED patterns и остальные эксплуатационные значения.
2. **Device topology/identity** — локальная аппаратная идентичность, выбранный master и порядок slave. Эти данные не должны слепо копироваться одинаково на четыре устройства.
3. **Portal security/secrets** — логины, password hashes и секреты. Их нельзя смешивать с переносимым runtime profile.
4. **Immutable bundle defaults** — начальные значения, поставляемые вместе с кодом версии. Они используются только при первом запуске версии или явном factory reset этой версии.

Предпочтительный вариант:

- core становится единственным владельцем и writer эксплуатационных настроек;
- portal только читает/изменяет их через core API;
- engine получает путь из core/env и больше не строит `bmi30_config.json` рядом с `__file__`;
- все записи выполняются атомарно с file lock, schema version и проверкой JSON;
- systemd явно задаёт одинаковый `BMI30_CONFIG_JSON` для core и portal;
- credentials остаются в отдельном root-only файле.

Для состояния версии нужен mutable sidecar, не изменяющий SHA immutable bundle. Возможная структура:

```text
/var/lib/bmi30/
  versions/
    2026-07-15-0832/settings.json
    2026-07-16-1250/settings.json
  device_identity.json
  portal_secrets.json
```

Допустим и workspace-вариант `host/bmi30_version_state/<bundle-id>/`, если именно этот каталог будет явно включён в device recovery. Важно не конкретное имя каталога, а разделение immutable bundle и mutable per-version state.

### 3.7. Требуемое поведение переключателя версии

Перед переключением:

1. запросить у работающего core нормализованный полный snapshot;
2. проверить schema и bundle ID;
3. атомарно записать его в sidecar текущей версии;
4. только после успешного checkpoint останавливать службы.

После переключения:

1. если sidecar выбранной версии существует — загрузить его;
2. если sidecar отсутствует — один раз инициализировать его defaults из bundle;
3. запустить core и применить настройки;
4. прочитать status/readback и проверить ключевые поля;
5. при ошибке выполнить rollback runtime и конфигурации как одну транзакцию.

Нужны отдельные операции:

- `Save current settings for this version`;
- `Reset this version to bundle defaults`;
- `Copy settings from version A to version B`;
- `Export/import version profile` с проверкой совместимости schema.

### 3.8. Требуемое поведение cloud backup/restore

Следует разделить два вида облачных данных:

- **общий firmware release** — одинаковый код и immutable bundle для всех устройств, без локальных ролей и секретов;
- **device recovery state** — per-version sidecars, calibration и topology конкретного Raspberry/STM32, привязанные к стабильной аппаратной identity.

Device recovery должен содержать manifest как минимум с:

- Raspberry serial/host identity;
- STM32 UID96;
- bundle IDs;
- schema versions;
- SHA-256 каждого state-файла;
- временем snapshot;
- перечнем включённых и намеренно исключённых секретов.

При восстановлении нельзя безусловно применять role/node ID чужого устройства. Нужна проверка совпадения identity либо явное подтверждённое переназначение.

## 4. Проблема 2: звуки при неактивном оптическом датчике

### 4.1. Что подтверждено в активном engine

В `BMI30.200.py.2026-07-15-0832` обнаружены следующие дефекты.

1. `optic_reaction_enabled` всегда стартует с `False` и не восстанавливается из сохранённой конфигурации.
2. `_set_optic_reaction_enabled()` меняет только переменную в памяти и не сохраняет её.
3. `_fire_beep()` при включённой реакции проверяет только локальный `flags_runtime bit 0x0020`.
4. Для slave это неверный источник: согласно текущему protocol master optic должен читаться из `flags_runtime bit 0x0080`.
5. Если STAT отсутствует или старше трёх секунд, `_current_optic_active()` возвращает `None`, а `_fire_beep()` блокирует только строгое `False`. То есть неизвестное/устаревшее состояние работает как fail-open и разрешает звук.
6. `_beep_hold_start()` вообще не проверяет оптический затвор.
7. Периодический sound guard проверяет mode, кнопку sound и detector hold, но не проверяет оптику. Уже начатый repeating/hold PWM может продолжаться после закрытия/устаревания optic gate до другого события остановки.
8. `_group_led_detection_allowed()` проверяет только `mode >= 6`, поэтому host-side LED detection path также не имеет role-aware optic gate.

Это даёт несколько независимых сценариев ложного звука:

- после restart галочка фактически выключена, хотя пользователь ранее её включал;
- на slave локальный detector/optic источник используется вместо свежего master optic bit;
- краткая потеря или устаревание STAT открывает затвор;
- звук уже запущен и не останавливается немедленно при закрытии gate;
- hold/repeat path обходит первоначальную проверку.

### 4.2. Важная найденная регрессия

В архивном engine `host/BMI30.200.py.2026-07-13-1046-slave-master-optic-gate` уже реализованы необходимые принципы:

- сохранение `optic_reaction_enabled`;
- определение текущей роли;
- master использует local optic bit `0x0020`;
- slave использует только master optic bit `0x0080`;
- неизвестная роль и stale STAT закрывают gate;
- gate проверяется перед initial beep и hold;
- состояние gate доступно для диагностики.

Активная версия содержит более простую старую логику. Исправление следует переносить осознанно в новую нейтральную пару core/engine, а не переключать весь runtime на архивный core-only snapshot.

### 4.3. Что показала live-диагностика

В момент выборки core API показывал:

- `mode=6`;
- `sound.enabled=true`;
- `optic.reaction_enabled=true` только в live-памяти;
- роль `master`, код `M03`;
- четыре устройства по `total_devices`;
- текущий local optic был активен.

Поэтому именно физический случай «optic inactive, но слышен звук» в ходе read-only исследования не воспроизводился: для этого пришлось бы менять состояние датчика или настройки. Причина, однако, подтверждается статическим анализом всех путей запуска/удержания звука и расхождением saved/live settings.

### 4.4. Предлагаемое исправление

Нужна одна функция принятия решения, например `optic_detection_indication_allowed()`, которую обязаны использовать все sound/LED paths.

Правила:

- если checkbox выключен — optic gate обходится;
- если checkbox включён и роль master — разрешение только по свежему local bit `0x0020`;
- если checkbox включён и роль slave — разрешение только по свежему master bit `0x0080`;
- `any optic` bit `0x0100` не должен разрешать звук конкретного slave;
- неизвестная роль, отсутствующий STAT или stale STAT — fail-closed;
- при переходе gate `open -> closed` PWM и repeating sequence останавливаются немедленно;
- gate проверяется в initial fire, hold start, repeat/retry, periodic guard и local LED detection;
- manual sound/LED test должен иметь отдельный явно обозначенный режим и не маскироваться под detector event.

В status API нужны поля:

- `enabled`;
- `allowed`;
- `source`;
- `sync_role`;
- `local_optic_active`;
- `master_optic_active`;
- `stat_age_s`;
- `sound_output_active`;
- `led_commanded` и `led_actual`.

### 4.5. Обязательная матрица тестов

Для master и каждого slave отдельно:

| Checkbox | Роль | Свежий нужный optic bit | STAT | Ожидаемый sound/LED |
|---|---|---:|---|---|
| off | любая | 0/1 | fresh/stale | detector indication работает без optic gate |
| on | master | local=0 | fresh | запрещено |
| on | master | local=1 | fresh | разрешено |
| on | slave | master=0 | fresh | запрещено |
| on | slave | master=1 | fresh | разрешено |
| on | любая | любое старое значение | stale/missing | запрещено |
| on | unknown | любое | fresh/stale | запрещено |

Дополнительно проверить закрытие gate во время уже активного repeating sound и detector hold.

## 5. Проблема 3: после restart случайный master и повторяющиеся номера slave

### 5.1. Подтверждённое текущее поведение

Документация firmware прямо указывает: по умолчанию устройства работают в auto-role и выбирают master/slave через RS485 sync/UID arbitration. Это детерминировано относительно внутренних UID/таймингов firmware, но является «случайным» относительно выбора пользователя, потому что предпочтительный master нигде постоянно не задан.

Для фиксированной топологии protocol уже поддерживает правильные команды:

- master: `SET_SYNC_MODE [0x00]`;
- slave: `SET_SYNC_MODE [0x01, node_id]`;
- slave ID: `1..31`, уникальный;
- возврат к auto: `[0x03]` или `[0xFF]`.

Однако в активной host-системе:

1. нет сохранённого `master identity` и упорядоченного списка членов группы;
2. Portal endpoint отправляет назначение только live и не сохраняет его;
3. активный core не содержит обработчика action `sync_mode`, хотя Portal его вызывает;
4. engine `_send_sync_mode()` принимает только один байт mode и не умеет атомарный payload `[slave, node_id]`;
5. startup/reconnect path не применяет желаемую topology;
6. отсутствует обязательный readback `host_forced`, role и local node ID;
7. `SET_RS485_ID` в документации назван временным, поэтому после reset его должен заново задавать host.

Таким образом, после полного reboot/STM32 reset устройства естественно возвращаются к auto-role.

### 5.2. Что показал текущий device cache

В одной live-выборке одновременно наблюдались:

- роль/code: `M03`;
- `total_devices=4`;
- authoritative `sync_seen_mask=0x00000007`, то есть текущий компактный набор slave 1, 2, 3;
- `local_node_id=20` в EVT1 master state;
- в накопленном `sensors.remote` оставались старые строки node 1, 6, 9, 12, 15, 28 и отдельные несовпадения slot ID со status byte.

Эта выборка не доказывает, что прямо в этот момент на RS485 реально было шесть slave или повторяющиеся актуальные ID: authoritative mask показывал ровно три slave. Она доказывает другую ошибку — aggregate cache сохраняет устаревшие remote rows после изменения topology, поэтому Portal может показывать старые/противоречивые устройства и создавать впечатление повторов.

Сообщённые пользователем физические повторы ID всё равно правдоподобны, потому что host не закрепляет уникальные ID после restart. Для строгого разделения «реальный duplicate на шине» и «stale UI row» нужен одновременный лог всех четырёх устройств.

### 5.3. Предлагаемая модель фиксированной topology

Topology должна опираться на стабильную аппаратную identity, а не на IP, hostname или порядок запуска.

Предлагаемый общий group profile:

```json
{
  "schema": 1,
  "group_id": "group-1",
  "master_uid96": "<UID выбранного STM32>",
  "ordered_members": [
    "<UID master>",
    "<UID slave 1>",
    "<UID slave 2>",
    "<UID slave 3>"
  ]
}
```

Каждое устройство находит собственный STM32 UID96 в этом списке:

- совпало с `master_uid96` — применить forced master;
- иначе slave ID равен порядковому номеру среди non-master members: `S01`, `S02`, `S03`;
- identity отсутствует, дублируется или профиль невалиден — не входить молча в auto-role; показать fault и безопасно ждать исправления.

Так один и тот же group profile можно доставить всем четырём устройствам, но каждое вычислит собственное уникальное назначение. Локальный override также возможен, но он должен быть привязан к UID и проверен против общего профиля.

### 5.4. Startup/reconnect state machine

После появления USB/STM32 host должен:

1. прочитать UID96;
2. загрузить и провалидировать group profile;
3. вычислить локальную роль и slave ID;
4. отправить master `[0x00]` либо slave `[0x01, id]` одной атомарной командой;
5. запросить LCDS/EVT1/STAT readback;
6. проверить `host_forced`, фактическую роль, `local_node_id` и ожидаемый код;
7. повторить применение после каждого STM32 reset, USB reconnect и firmware recovery;
8. не объявлять устройство ready до успешного readback.

Для группы из четырёх устройств ожидаемый устойчивый результат:

- выбранное устройство: master, дисплей `M03`;
- остальные устройства: `S01`, `S02`, `S03` без повторов;
- `sync_seen_mask` master: `0x00000007`;
- `total_devices=4`.

### 5.5. Исправление диагностического cache/UI

Необходимо разделить:

- authoritative current topology из свежего EVT1/STAT mask;
- historical identity rows из RS485 identity scan.

Remote sensor list должен заменяться новым полным STAT snapshot либо удалять строки, которых нет в свежем `sync_seen_mask`. У каждой строки нужны `updated_at`, `age_s`, `current=true/false`. Исторические RID1-записи нельзя рисовать как активные устройства без текущего mask bit.

### 5.6. Обязательные тесты topology

1. Одновременное включение четырёх устройств не менее 20 раз.
2. Разный порядок включения всех четырёх устройств.
3. Restart одного Raspberry без reset остальных.
4. Reset STM32 одного slave.
5. Reset master при работающих slave.
6. Краткий разрыв RS485.
7. USB reconnect на каждом устройстве.
8. Временное отсутствие одного slave и его позднее возвращение.
9. Проверка отсутствия duplicate slave ID по readback всех четырёх устройств.
10. Проверка, что выбранный master не меняется без явного изменения group profile.
11. Проверка очистки stale remote rows в Portal.

## 6. Какие параметры должны войти в version settings

Минимально требуется сохранить и восстановить:

- Operating mode и параметры потока, если они должны быть startup defaults;
- `avg_n`;
- Automatic threshold для обоих каналов;
- manual/effective threshold inputs;
- Noise averaging window;
- noise up/down и единицы;
- Detection confirmations;
- detector channel enable;
- burst gate/blank/max ratio;
- named filters и их параметры;
- peak position limits;
- Work/Acquisition/Detection adaptation timing;
- sound enabled, volume и frequencies;
- optic reaction checkbox и optic hold;
- group LED patterns;
- TX/TIM2 startup preference, если это пользовательская настройка;
- остальные UI-параметры, которые сейчас пишутся в `bmi30_config.json`.

Не следует автоматически включать в переносимый общий version profile:

- portal passwords/hashes;
- Wi-Fi/RDP secrets;
- Raspberry/STM32 identity;
- master/slave assignment без identity mapping;
- transient test-tone flags;
- runtime counters, live detector threshold, hold state и stale cache.

Перед реализацией нужен формальный JSON schema с классификацией каждого существующего ключа: version setting, device setting, secret или transient.

## 7. Предлагаемый порядок будущей реализации

### Этап A. Каноническая конфигурация

1. Инвентаризировать все читаемые/записываемые ключи.
2. Создать schema и migration из существующих трёх JSON.
3. Сделать core единственным writer эксплуатационной конфигурации.
4. Перевести engine и portal на один API/path.
5. Разделить runtime settings, topology и secrets.

### Этап B. Per-version state и cloud recovery

1. Добавить mutable sidecar по bundle ID.
2. Добавить checkpoint/restore в switch transaction.
3. Включить sidecars в отдельный device recovery archive.
4. Добавить identity manifest и restore validation.
5. Не включать device identity в общий firmware release.

### Этап C. Оптический затвор

1. Перенести role-aware fail-closed решение из проверенного архивного snapshot в новую активную пару.
2. Подключить его ко всем sound/LED paths.
3. Добавить немедленную остановку output при закрытии gate.
4. Добавить status diagnostics и матричные тесты.

### Этап D. Фиксированная topology

1. Добавить group profile, привязанный к UID96.
2. Реализовать core action для atomic `SET_SYNC_MODE [role, node_id]`.
3. Применять назначение на startup/reconnect/reset.
4. Проверять readback и блокировать ready при несоответствии.
5. Очистить смешение current topology и historical cache.

### Этап E. Четырёхузловой приёмочный тест

Проверить сохранение каждой версии, cloud recovery, master/slave topology и optic sound/LED как одну систему. Только после успешного soak test создавать завершённый snapshot с topic suffix и обновлять version registry.

## 8. Файлы, которые вероятно потребуют изменения позже

Это только предварительный список; в рамках данного исследования они не менялись.

- новый активный core `BMI30.001.py.<new-date-time>`;
- matching engine `BMI30.200.py.<new-date-time>`;
- `hotspot_info_server.py`;
- `host/usb_vendor/usb_stream.py`;
- `switch_bmi30_split_versions.sh`;
- `utilities/create_bmi30_split_bundle.sh`;
- `utilities/cloud_sync_common.sh`;
- recovery backup/restore scripts;
- systemd/environment configuration;
- protocol/host documentation;
- automated tests и `docs/BMI30_version_registry_google_sheet.csv` после фактической реализации.

## 9. Риски, которые нельзя игнорировать

- Нельзя записывать mutable settings внутрь immutable bundle без пересчёта SHA и изменения модели snapshot.
- Нельзя копировать один локальный `role=master` config на все четыре устройства через общий cloud release.
- Нельзя объединять portal secrets с переносимым version profile.
- Нужна защита от одновременной записи portal и engine, иначе возможна потеря соседних ключей при read-modify-write.
- При миграции нельзя выбирать «самый новый файл» только по mtime: разные файлы содержат разные группы ключей.
- Для DC timing необходим device readback, а не только успешная запись JSON.
- Для topology недостаточно красивого `Mxx/Sxx` в UI; нужны forced flag, UID и node ID readback.
- Для optic gate нельзя использовать stale aggregate cache или `any optic` как разрешение slave sound.

## 10. Критерии готовности будущего исправления

Работа считается завершённой только если одновременно выполнено следующее:

1. После restart core все перечисленные настройки остаются прежними.
2. После переключения A -> B -> A версия A получает именно свои последние настройки, а B — свои.
3. Device recovery из облака восстанавливает per-version settings с проверкой identity и SHA.
4. Общий firmware update не размножает master/slave identity на другие устройства.
5. При optic gate enabled неактивный/stale нужный датчик никогда не разрешает sound/LED.
6. Уже активный звук немедленно останавливается при закрытии optic gate.
7. После любого порядка перезапуска выбранный UID остаётся master, остальные получают S01..S03 без повторов.
8. Portal не показывает stale remote rows как текущие устройства.
9. Все четыре устройства проходят многократный power-cycle/reconnect soak test.

