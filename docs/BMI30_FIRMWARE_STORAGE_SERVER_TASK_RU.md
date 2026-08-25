# Задание для Codex непосредственно на сервере BMI30 Hub

Скопируйте весь текст внутри блока ниже в новую задачу Codex, запущенному
непосредственно на production-сервере `www.teiots.net` с административными
правами.

```text
Ты работаешь непосредственно на production-сервере BMI30 Hub
`www.teiots.net`. Нужно добавить на этот сервер хранилище файлов обновления
Raspberry BMI30 и безопасную HTTPS-раздачу этих файлов.

Это строго серверная задача.

Не изменяй код и настройки Raspberry BMI30. Не подключайся к Google Drive и не
переноси Google Drive на сервер. Не реализуй на сервере выбор между Google Drive
и новым хранилищем. Google Drive продолжит работать отдельно; позднее клиентские
утилиты BMI30 будут публиковать одинаковый release в оба места и постепенно
переводить приборы на сервер.

## Исходные данные

- Production Hub: `https://www.teiots.net/bmi30`.
- Reverse SSH работает через `www.teiots.net:2222`.
- Существующие Hub UI/API, enrollment, heartbeat, approval и reverse tunnels
  нельзя ломать или надолго останавливать.
- Один BMI30 release состоит из двух файлов:
  1. `bmi30_latest.env` — небольшой текстовый marker;
  2. `bmi30_backup_YYYYMMDD_HHMMSS.tar.gz` — полный firmware archive.
- В marker указаны имя архива и его SHA-256. Raspberry сначала читает marker,
  затем скачивает архив и проверяет SHA-256 до применения.
- Новый сервер должен хранить и отдавать эти файлы без изменения их формата.

Для первой последующей загрузки подготовлен release:

- `FIRMWARE_VERSION=2026-08-14-151255`
- `FIRMWARE_BUNDLE_ID=2026-08-14-1512`
- `ARCHIVE_NAME=bmi30_backup_20260814_152221.tar.gz`
- `ARCHIVE_SIZE=54315190`
- `ARCHIVE_SHA256=77599c1dd885d71e80a6a08083d7b404411878836621911c8d584f7dceb05c1f`

Эти значения нужны для будущей проверки. Реальный архив пока может отсутствовать
на сервере. Не создавай фиктивный production latest и не объявляй этот release
активным, пока не будут переданы настоящие marker и archive.

## 1. Сначала обследуй сервер

До любых изменений:

1. Определи ОС и версию.
2. Определи текущий web stack: nginx, Apache, IIS, Caddy, приложение Hub,
   reverse proxy и владельца HTTPS/443.
3. Найди service/unit существующего BMI30 Hub и его конфигурацию.
4. Проверь свободное место, файловую систему и существующую backup policy.
5. Проверь текущие firewall rules и listening ports.
6. Найди используемый механизм аутентификации Hub, но не выводи токены,
   приватные ключи, пароли или connection strings.
7. Покажи краткий отчёт обследования.
8. Сделай резервные копии всех конфигов и файлов, которые планируешь менять.

Не перезапускай существующие службы до проверки новых конфигураций штатными
syntax/config test командами.

## 2. Создай серверное хранилище

Выбери постоянный data volume с достаточным местом. Для Linux предпочтительна
структура:

- `/srv/bmi30-firmware/releases` — опубликованные неизменяемые архивы;
- `/srv/bmi30-firmware/staging` — незавершённые загрузки `.part`;
- `/srv/bmi30-firmware/metadata` — latest marker, история и audit;
- `/var/log/bmi30-firmware` — журнал, если не используется journald.

Для Windows создай эквивалентную структуру на постоянном data volume.

Требования:

1. Создай отдельный непривилегированный service account без интерактивного
   входа и административных групп.
2. `releases` читается download-службой, но изменяется только publish-службой.
3. `staging` не должен раздаваться через HTTP.
4. Запрети directory listing.
5. Секреты храни вне web root с правами `0600` или эквивалентными ACL.
6. Не запускай firmware application от root без строгой необходимости.
7. Добавь контроль свободного места и предупреждения при 80% и 90% заполнения.

## 3. Реализуй HTTPS download

Добавь под существующим сертификатом и портом 443 маршруты:

- `GET|HEAD https://www.teiots.net/bmi30/firmware/bmi30_latest.env`
- `GET|HEAD https://www.teiots.net/bmi30/firmware/bmi30_backup_<YYYYMMDD_HHMMSS>.tar.gz`

Не открывай для этого новый публичный порт. Не меняй SSH/2222 и tunnel ports.

Требования к marker:

- `Content-Type: text/plain; charset=utf-8`;
- `Cache-Control: no-store, no-cache, must-revalidate`;
- отдавать сохранённые bytes без конвертации в JSON и без изменения shell
  escaping;
- marker всегда должен ссылаться на реально существующий проверенный archive.

Требования к archive:

- `Content-Type: application/gzip`;
- точный `Content-Length`;
- `ETag` на основе SHA-256;
- поддержка `HEAD`;
- поддержка `Range` и корректного ответа `206 Partial Content`;
- потоковая отдача без загрузки всего архива в память приложения;
- разрешены только имена по regex
  `^bmi30_backup_[0-9]{8}_[0-9]{6}\.tar\.gz$`;
- запрещены slash, `..`, произвольный filesystem path и target из query string.

При временной ошибке возвращай `503` и `Retry-After`, при отсутствии файла —
`404`. Не отдавай stack trace и внутренние пути.

## 4. Реализуй авторизацию

Firmware archive не должен стать публичной раздачей исходников.

1. Сначала проверь, можно ли безопасно использовать существующий middleware Hub
   для approved DEVICE_ID + device API token.
2. Если это нельзя сделать изолированно без риска для Hub, создай отдельный
   read-only Bearer credential для скачивания firmware.
3. Для публикации создай отдельный publisher credential с write scope.
4. Read credential не может публиковать, менять latest или удалять файлы.
5. Publisher credential не выводи в отчёте и логах.
6. Токены передаются только через HTTPS header `Authorization: Bearer ...`.
7. Запрещены token в URL/query string и логирование Authorization header.
8. Сравнивай секреты constant-time.
9. Добавь разумный per-device/per-IP rate limit, но не маленький глобальный лимит,
   который помешает группе приборов одновременно скачать один archive.

## 5. Реализуй атомарную публикацию

Добавь защищённый endpoint:

`POST https://www.teiots.net/bmi30/api/v1/firmware/publish`

Предпочтительный формат — multipart с полями `marker` и `archive`. Допустим
эквивалентный двухфазный API, если он лучше соответствует существующему Hub, но
публикация обязана оставаться одной атомарной серверной транзакцией.

Порядок работы:

1. Возьми server-side lock: одновременно допускается одна publish transaction.
2. Потоково запиши входные файлы в уникальные `.part` внутри `staging`.
3. Marker ограничь, например, 64 KiB. Archive limit задай не меньше 2 GiB.
4. До загрузки проверь свободное место.
5. Вычисли SHA-256 archive на сервере во время записи.
6. Разбери только разрешённые ключи marker как данные. Никогда не выполняй marker
   через shell/source/eval.
7. Проверь, что `ARCHIVE_NAME` соответствует фактически загруженному имени и
   regex, а вычисленный SHA совпадает с `ARCHIVE_SHA256`.
8. Проверь gzip/tar без исполнения содержимого:
   - один безопасный top-level project directory;
   - нет absolute paths и `..`;
   - нет device nodes, FIFO и выходящих наружу symlink/hardlink;
   - есть `host/bmi30_split_active_version.env`;
   - есть `host/bmi30_split_bundles/FIRMWARE_BUNDLE_ID/manifest.env`;
   - есть `SHA256SUMS` выбранного bundle;
   - bundle ID в active env, manifest и marker совпадает;
   - файлы bundle соответствуют SHA256SUMS.
9. Проверку реализуй server-owned кодом. Не запускай скрипты из загруженного
   архива.
10. Если archive с тем же именем и тем же SHA уже существует, верни idempotent
    success. Если имя совпало, а SHA отличается — `409 Conflict`.
11. После полной проверки атомарно перемести archive из staging в releases.
12. Выполни fsync данных и каталога, затем атомарно замени latest marker через
    temp + rename. Marker обновляется строго последним.
13. При любой ошибке прежний latest остаётся неизменным, `.part` удаляется, а
    API возвращает короткий JSON с корректным 4xx/5xx.

Успешный JSON должен содержать:

- `firmware_version`;
- `bundle_id`;
- `archive_name`;
- `archive_sha256`;
- `archive_size`;
- `published_at`;
- `latest_url`.

Добавь отдельную защищённую административную операцию, которая может назначить
latest один из уже существующих проверенных архивов. Она меняет только marker,
не удаляет новые архивы и обязательно записывается в audit log.

## 6. История, retention и backup

1. Опубликованные архивы immutable и не перезаписываются.
2. Сохраняй историю marker: version, bundle ID, archive, SHA-256, время и
   publisher identity без токена.
3. Храни не меньше 10 последних release и не меньше 30 дней.
4. Никогда автоматически не удаляй current latest, предыдущий latest и pinned
   releases.
5. Retention выполняй отдельной scheduled job. Сначала сформируй список, затем
   удаляй только точные проверенные пути.
6. Не используй широкие recursive delete или непроверенные glob targets.
7. Настрой backup releases, metadata/latest и audit либо включи их в существующую
   server backup policy.
8. Проверь восстановление одного release из backup без изменения production
   latest.

## 7. Служба и диагностика

Добавь отдельную service unit/application module либо изолированный компонент
внутри Hub — выбери после обследования существующей архитектуры.

Требования:

- автозапуск после reboot;
- restart-on-failure с ограничением частоты;
- отдельный status/health endpoint или административный CLI;
- status показывает service state, current version/bundle/archive/SHA,
  archive count, staging count, disk free, последнюю публикацию и последнюю
  ошибку;
- status не показывает секреты;
- logs содержат result, version, archive, bytes, duration, authenticated actor и
  HTTP status, но не Authorization;
- настроены log rotation и ограничение размера журналов.

## 8. Серверные проверки приёмки

До объявления готовности выполни:

1. Unit/config tests нового компонента.
2. Syntax/config test web server до reload/restart.
3. Проверку, что существующие Hub UI/API, heartbeat, enrollment и reverse SSH
   tunnel продолжают работать.
4. Неавторизованные download и publish получают `401/403`.
5. Авторизованные `GET` и `HEAD` marker/archive работают через публичный HTTPS.
6. Range request возвращает `206` и корректный `Content-Range`.
7. Скачанный по публичному HTTPS archive имеет исходные размер и SHA-256.
8. Повторная публикация тех же bytes idempotent.
9. То же имя с другим SHA получает `409`.
10. Неверный SHA, повреждённый gzip, path traversal, неправильный bundle ID и
    archive без полного bundle отклоняются, а latest не меняется.
11. Имитируй обрыв upload: `.part` не раздаётся, latest остаётся прежним.
12. Две параллельные публикации сериализуются lock-ом.
13. Административное назначение предыдущего archive меняет marker, но сохраняет
    все архивы.
14. После reboot firmware service, HTTPS routes, Hub и tunnel services работают.

Если реальный BMI30 release ещё не передан, проведи проверки на безопасном
server-generated fixture, но не назначай его production latest. Оставь storage
в состоянии `ready, no production release`.

## 9. Итоговый отчёт

Создай на сервере текстовый отчёт и сообщи его полный путь. Укажи:

- ОС и существующий web stack;
- что именно добавлено;
- service/application names;
- пути releases, staging, metadata, logs, config и backup;
- публичные latest, archive и publish URLs;
- выбранную схему read/write authentication без значений секретов;
- безопасный способ отдельно передать credentials владельцу;
- точный curl publish example с placeholder token;
- точные curl GET, HEAD и Range examples;
- response format и лимиты size/concurrency/retention;
- результаты всех acceptance tests с HTTP status, размером и SHA-256;
- команды status/restart/logs;
- процедуру ротации credentials;
- полный rollback всех серверных изменений;
- перечень данных, которые потребуются разработчику Raspberry для подключения к
  готовому API.

Не изменяй Google Drive. Не изменяй Raspberry. Не публикуй фиктивный production
latest. Результат этой задачи — готовое, проверенное server-side хранилище и
точный отчёт для последующей клиентской интеграции.
```
