# Задание: два источника обновлений BMI30 на Raspberry

Это клиентская часть перехода после выполнения серверного задания
`docs/BMI30_FIRMWARE_STORAGE_SERVER_TASK_RU.md`. Google Drive должен продолжать
работать для старых приборов и как резерв; сервер `www.teiots.net` добавляется
постепенно, по группам устройств.

```text
Нужно реализовать в проекте BMI30 два полностью поддерживаемых firmware backend:
существующий Google Drive через rclone и новый HTTPS storage на production Hub.
Работай до end-to-end тестов обновления и отката, но не отключай Google Drive и
не переключай весь парк приборов одной операцией.

Перед изменениями прочитай серверный отчёт. Не выдумывай URL, authentication или
response format: используй подтверждённые сервером значения. Проверь активную
websplit-версию по `host/bmi30_split_active_version.env`; legacy monolith не
изменяй. Сохрани локальные device identity, настройки, rclone credentials и
server tokens вне общего firmware archive.

Затрагиваемые компоненты:
- `utilities/backup_to_cloud.sh` — единая сборка release и публикация;
- `utilities/update_from_cloud.sh` — выбор источника, download и activation;
- `utilities/cloud_sync_now.sh` и `utilities/cloud_sync_common.sh`;
- `utilities/backup_status.sh`, `utilities/menu.sh`, `utilities/README.md`;
- `utilities/portal_firmware_operation.sh`;
- `hotspot_info_server.py` — Portal Update/Rollback и отображение состояния;
- system config/installer для persistent backend settings и read credential;
- tests и журнал websplit-версий.

## 1. Режимы клиента

Добавь persistent конфигурацию вне release archive, например
`/etc/bmi30/firmware_sources.env`, с правами root и группы, которой достаточно
для Utilities/Portal updater. Не сохраняй секрет в `host/bmi30_config.json`,
bundle, cloud archive, logs или API/status.

Поддержи режимы:
- `gdrive` — читать и скачивать только из существующего Google Drive. Это режим
  совместимости для старых приборов;
- `dual-check` — проверить оба marker и показать расхождения, но устанавливать
  release через Google Drive. Это первый этап миграции;
- `server-first` — проверить оба marker, выбрать самую новую согласованную
  версию, одинаковый release скачивать сначала с сервера, при транспортной
  ошибке — из Google Drive;
- `server-only` — использовать только сервер; режим ручной диагностики и
  будущего применения, не делать его default сейчас.

Первоначальный default после установки нового кода — `gdrive`. Переключение
конкретного прибора выполняется явно и сохраняется между firmware updates.

Минимальные несекретные параметры:
- mode;
- server base URL;
- server auth mode и путь к token file;
- Google remote/folder/marker из существующего config;
- connect/read/total timeout;
- migration cohort/channel label.

## 2. Единая модель release

Один release создаётся ровно один раз и имеет одни и те же bytes в обоих
backend:
- одинаковые FIRMWARE_VERSION и FIRMWARE_BUNDLE_ID;
- одинаковые ARCHIVE_NAME, размер и ARCHIVE_SHA256;
- одинаковый `bmi30_latest.env`;
- одинаковый tar.gz, без повторной упаковки для второго backend.

Раздели текущий publisher на стадии `build`, `upload archive`, `verify archive`,
`commit marker`, чтобы один локальный артефакт можно было опубликовать в Google и
на сервер. Поддержи publish modes `gdrive`, `server` и `dual`.

В `dual`:
1. собрать archive/marker один раз;
2. idempotent загрузить archive в оба backend;
3. проверить имя, размер и SHA в обоих;
4. только затем обновить latest marker в обоих;
5. повторно прочитать marker и проверить полное совпадение;
6. при частичной ошибке показать backend-specific status и не писать общий
   success. Повтор той же команды должен безопасно завершить незаконченный
   release без новой упаковки и новой версии.

Никогда не удаляй рабочую копию Google автоматически. Remote pruning выполняй
только отдельно в каждом backend, не удаляя current, previous и pinned release.

## 3. Выбор release для обновления

Реализуй единый нормализованный marker object и независимые backend adapters.
Для каждого источника проверяй формат, version, bundle ID, archive basename,
SHA-256 и signature version до принятия решения.

Правила безопасности:
1. При одинаковой FIRMWARE_VERSION значения bundle ID, archive name и SHA должны
   совпадать. Любое расхождение — `release conflict`; Update блокируется.
2. Если версии разные, выбери самую новую валидную version. Не выдавай старый
   server marker за обновление, когда Google содержит более новый release, и
   наоборот.
3. Transport fallback разрешён только на backend, где опубликован тот же
   выбранный ARCHIVE_NAME с тем же SHA. Нельзя после ошибки нового server release
   молча установить более старый Google release.
4. Уже скачанный archive можно переиспользовать только после SHA-256 проверки.
5. HTTPS server download требует проверку системного CA, hostname и
   Authorization header. Запрещены `curl -k`, token в URL и логирование token.
6. Google adapter продолжает использовать существующие rclone config/folder и
   прежний marker contract.
7. Временная недоступность одного backend не является conflict. Покажи degraded
   status и используй второй, если в нём есть выбранный идентичный release.
8. Если ни один источник не даёт полностью проверяемый release, текущая версия
   остаётся активной.

## 4. Обновление и откат

Оба backend после выбора/download должны входить в одну общую transaction:
snapshot, apply archive, validate bundle, activate, verify services, write
update state и rollback state. Не дублируй activation logic по источникам.

Обязательный контракт:
- перед каждым обновлением активна A;
- Update устанавливает реально более новую N;
- Rollback возвращает A независимо от того, откуда пришла N;
- после Rollback повторный Update снова сохраняет текущую A как rollback target,
  даже если project files уже совпадают с N и требуется только повторная
  activation runtime bundle;
- при неуспешном Update A остаётся активной, а прежний rollback state не
  подменяется незавершённой transaction;
- после успешного Rollback он помечается consumed; следующий Update создаёт
  новую точку rollback.

Сохраняй в update/operation state выбранные release identity и transport:
`selected_version`, `bundle_id`, `archive`, `sha256`, `marker_sources`,
`download_source`, `fallback_used`, timestamps и результат. Секретов там быть
не должно.

## 5. Portal и Utilities

Utilities должны позволять:
- показать статус обоих backend и выбранный mode;
- проверить updates без установки;
- установить выбранный release;
- принудительно переустановить тот же release для диагностики;
- сменить mode только явной административной командой;
- опубликовать release в Google, server или dual с понятным итогом каждого.

Portal Firmware card должна показывать:
- текущую локальную version/bundle;
- Google latest и server latest отдельно;
- выбранную итоговую release и предпочтительный download source;
- `Google unavailable`, `Server unavailable`, `Fallback to Google` или
  `Release conflict` без технических секретов;
- Update только когда новая release валидна;
- Rollback target — версию, активную перед последним успешным Update.

Кнопка Portal и пункт Utilities обязаны вызывать один и тот же updater и давать
одинаковый результат. Старые selectable Portal bundles должны продолжать
вызывать текущий root updater после переключения версии.

## 6. Постепенная миграция

Реализуй и задокументируй этапы:
1. `gdrive`: весь парк работает как сейчас; сервер только подготовлен.
2. `dual-check`: тестовые устройства сравнивают marker, но скачивают из Google.
3. `server-first`: несколько DEVICE_ID скачивают с сервера с Google fallback.
4. Расширять cohort группами только после успешных Update, reboot и Rollback.
5. Для обновлённых приборов server-first становится default; старые сохраняют
   gdrive без срочного вмешательства.
6. Google Drive не отключать в этой задаче. Решение о его отключении — отдельное
   после инвентаризации всего парка.

Выбор cohort должен быть persistent и привязан к реальному DEVICE_ID, но общий
firmware archive остаётся одинаковым для всех приборов. Не копируй identity или
server credential между Raspberry через firmware release.

## 7. Тесты

Добавь unit/integration tests с локальными fake backends без реальной публикации:
- Google only сохраняет старое поведение;
- server only скачивает marker/archive по HTTPS contract;
- одинаковый release в двух backend выбирается без conflict;
- одинаковая version с разным SHA блокируется;
- server старее Google и Google старее server;
- недоступность server с идентичным release вызывает Google fallback;
- server содержит новую N, Google только старую: ошибка server не приводит к
  установке старой Google версии;
- повреждённый archive/SHA/path/marker отклоняется;
- dual publisher создаёт archive один раз и выгружает те же bytes;
- partial dual publish повторяется idempotent;
- A -> N из Google -> Rollback A;
- A -> N с сервера -> Rollback A;
- A -> N -> Rollback A -> повторный Update N -> Rollback A;
- Portal и Utilities используют одну transaction;
- backend config/token не попадает в bundle/archive/status/logs.

После unit tests выполни контролируемый end-to-end на одном тестовом BMI30:
1. сохранить текущую A и подтвердить service health;
2. dual-publish новую N и проверить bytes/SHA в двух backend;
3. установить старую A;
4. обновить A -> N через Utilities в `server-first`;
5. откатить N -> A;
6. снова обновить A -> N кнопкой Portal;
7. снова откатить N -> A;
8. вернуть прибор на N;
9. повторить download с искусственно недоступным сервером и подтвердить Google
   fallback на тот же release;
10. проверить core/portal/agent/tunnel services, active env, Portal SHA и rollback
    state после каждого перехода.

## 8. Документация и журнал

Обнови Utilities README и создай отчёт миграционного теста с версиями, bundle,
archive SHA, выбранными backend, fallback и service status. При создании нового
websplit bundle обнови `docs/BMI30_version_registry_google_sheet.csv` подробной
русской записью и синхронизируй Google Sheet штатной командой.

Не удаляй существующий Google archive/marker и не делай server-first default для
всех устройств до явного решения владельца после пилотной группы.
```
