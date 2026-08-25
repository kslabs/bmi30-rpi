# Задание локальному ChatGPT: адаптация Raspberry для BMI30 Hub

## Цель

Добавить на Raspberry отдельный агент BMI30, который регистрируется на фирменном Hub, получает назначенный reverse SSH-порт и поддерживает туннель к локальному HTTP-интерфейсу устройства.

Рабочие компоненты BMI20 нельзя удалять, заменять или останавливать. Новый агент и новый tunnel service должны иметь отдельные файлы, systemd units, SSH-ключ и журнал. Переход с BMI20 выполняется только после успешной параллельной проверки BMI30.

## Адреса production

- Hub: `https://www.teiots.net/bmi30`
- check-in: `POST https://www.teiots.net/bmi30/api/v1/agent/checkin`
- SSH: `www.teiots.net:2222`
- SSH user: `bmi30-tunnel`
- Проверка TLS выполняется обычным системным CA-хранилищем. Не применять `-k`, `verify=False` или отключение проверки сертификата.

## Обязательный порядок работы

1. Провести read-only аудит ОС, действующих BMI20 services/timers/cron, локального HTTP-порта, текущих SSH-туннелей, файлов конфигурации и журналов.
2. Создать датированную резервную копию только тех файлов, которые предстоит изменить. Сохранить вывод `systemctl cat`, `systemctl status` и контрольные суммы.
3. Не изменять действующий BMI20. Создать отдельные имена, например `bmi30-agent.service`, `bmi30-tunnel.service`, `/etc/bmi30-agent/` и `/var/lib/bmi30-agent/`.
4. Сначала проверить агент вручную, затем systemd, затем перезагрузку Raspberry.
5. При ошибке читать stderr и `journalctl`; исправлять причину, а не отключать проверки безопасности.

## Постоянная идентичность и секреты

- `raspberry_serial` — аппаратный серийный номер именно текущей платы Raspberry:
  ровно 16 шестнадцатеричных символов в верхнем регистре. Читать его при каждом
  запуске из `/proc/cpuinfo` (`Serial`) или эквивалентного системного файла;
  значение из скопированного конфигурационного файла не использовать.
- `device_id` вычислять только как `BMI30-<RASPBERRY_SERIAL>`. Например, для
  серийного номера `0123456789ABCDEF` допустим только
  `BMI30-0123456789ABCDEF`. Произвольный сохранённый код, hostname, MAC-адрес,
  STM32 UID и случайный UUID использовать как идентичность Raspberry нельзя.
- Создать отдельный Ed25519 SSH-ключ без passphrase. Public key должен иметь комментарий `<DEVICE_ID>@bmi30-tunnel`.
- Создать один случайный API token длиной не менее 40 символов; хранить только root-readable (`0600`). Не пересоздавать при рестарте и не писать token в журнал.
- Каталог конфигурации и состояния — `0700`; приватный ключ и token — `0600`.

## Обязательное исправление для клонируемых флешек (13.08.2026)

Одна подготовленная SD-карта будет клонироваться на несколько Raspberry.
Поэтому агент обязан отличать перенос той же карты/образа на другую физическую
плату от обычного рестарта.

Добавить root-readable файл состояния, например
`/var/lib/bmi30-agent/bound_raspberry_serial`, и выполнять до первого check-in:

1. Прочитать фактический аппаратный серийный номер текущей Raspberry и
   нормализовать его в 16 заглавных hex-символов. Пустое, нулевое или иное
   значение считать фатальной ошибкой; не запускать туннель.
2. Сравнить фактический номер с `bound_raspberry_serial` и с суффиксом
   сохранённого `device_id`.
3. Если файл отсутствует, либо номера не совпадают, это первый запуск клона.
   Под файловой блокировкой и атомарной записью:
   - остановить только `bmi30-tunnel.service`;
   - сохранить датированную резервную копию только старого состояния BMI30;
   - установить `device_id=BMI30-<ФАКТИЧЕСКИЙ_SERIAL>`;
   - создать новый случайный API token (не копировать старый);
   - создать новую пару Ed25519 с комментарием
     `<НОВЫЙ_DEVICE_ID>@bmi30-tunnel` (не копировать старый приватный ключ);
   - удалить из состояния только старые назначенные Hub-порт и статус approval;
   - атомарно записать фактический номер в `bound_raspberry_serial`;
   - сохранить каталоги `0700`, token/private key/state `0600`.
4. Не удалять и не изменять файлы, ключи, services или конфигурацию BMI20.
5. Выполнить check-in с новой идентичностью. Устройство должно появиться в Hub
   как отдельное `Pending`; после одобрения сохранить собственный назначенный
   порт и запустить собственный туннель.

Hub теперь проверяет аппаратную связь строго. Ответ HTTP 409 вида:

```json
{
  "code": "hardware_identity_mismatch",
  "expected_device_id": "BMI30-0123456789ABCDEF",
  "reset_identity_required": true
}
```

означает, что карта содержит идентичность другой Raspberry. Агент должен
выполнить описанную выше локальную переинициализацию BMI30 и повторить check-in.
Нельзя бесконечно повторять запрос со старым ID, отключать проверку Hub или
использовать один SSH-ключ/API token на нескольких платах.

Перед финальным отчётом проверить на каждой клонированной Raspberry (секреты не
выводить):

```bash
actual_serial="$(awk -F': *' '/^Serial/{print toupper($2)}' /proc/cpuinfo)"
printf 'actual_serial=%s\nexpected_device_id=BMI30-%s\n' \
  "$actual_serial" "$actual_serial"
sudo cat /var/lib/bmi30-agent/bound_raspberry_serial
sudo ssh-keygen -lf /etc/bmi30-agent/id_ed25519.pub
sudo systemctl status bmi30-agent.service bmi30-tunnel.service --no-pager
sudo journalctl -b -u bmi30-agent.service -u bmi30-tunnel.service \
  --no-pager -n 150 | grep -Ev 'Authorization|api_token|PRIVATE KEY'
```

В отчёте показать фактический serial, вычисленный DEVICE_ID, fingerprint нового
SSH-ключа, HTTP-код check-in и статусы обоих BMI30 services. Token и приватный
ключ не показывать.

## Формат check-in

Заголовки:

```text
Authorization: Bearer <DEVICE_API_TOKEN>
Content-Type: application/json
```

Минимальный JSON:

```json
{
  "device_id": "BMI30-0123456789ABCDEF",
  "public_key": "ssh-ed25519 AAAA... BMI30-0123456789ABCDEF@bmi30-tunnel",
  "hostname": "raspberry-hostname",
  "raspberry_serial": "stable-hardware-serial",
  "model": "Raspberry Pi ...",
  "firmware_version": "stm32-application-version",
  "agent_version": "raspberry-bmi30-software-version",
  "local_ips": ["192.168.1.10"],
  "tunnel_service": {},
  "local_api": {}
}
```

Не включать API token в JSON, если он уже передан как Bearer. Не превышать 64 KiB.

## Актуальное задание устройству: передача версий (12.08.2026)

Устройство `BMI30-C9775FBAE` уже подключено и туннель работает, но версии
передаются не полностью. Фактически Hub получает:

- в check-in: `agent_version="0.2.1"`, `firmware_version` пустой;
- в `/api/status`: `firmware_release.version="2026-08-11-2115"` и
  `split_system.version="2026-08-11-2115"`;
- в `group_state` есть `stm32_uid96`, но версии прошивки STM32 нет.

Нужно исправить агент/локальный API, не затрагивая BMI20:

1. В `agent_version` check-in передавать реальную версию программной сборки
   Raspberry (`2026-08-11-2115` для текущей установленной сборки), а не версию
   самого регистрационного агента. Версию агента при необходимости передавать
   отдельным дополнительным полем `connector_version`.
2. Определить версию приложения STM32 из реального ответа/протокола STM32 и
   передавать её в `firmware_version`. Нельзя подставлять `stm32_uid96`,
   `signature_version`, дату Raspberry-сборки или придуманное значение.
3. В корневой JSON `/api/status` добавить однозначные поля:

```json
{
  "raspberry_firmware_version": "2026-08-11-2115",
  "stm32_firmware_version": "<реальная версия приложения STM32 или пустая строка>"
}
```

4. Если текущий протокол STM32 вообще не предоставляет версию, письменно
   указать это в отчёте и назвать команду/сообщение протокола, которое нужно
   добавить в прошивку STM32. До появления реальных данных оставлять строку
   пустой; Hub не должен угадывать версию.
5. После изменения проверить без вывода API token:

```bash
curl -fsS http://127.0.0.1/api/status | jq '{
  raspberry_firmware_version,
  stm32_firmware_version,
  firmware_release: .firmware_release.version,
  stm32_uid96: .group_state.stm32_uid96
}'

sudo systemctl restart bmi30-agent.service
sudo journalctl -b -u bmi30-agent.service --no-pager -n 100
```

Финальный отчёт устройству должен показать оба безопасных поля check-in (без
token и public key), оба поля `/api/status`, источник версии STM32 и статусы
`bmi30-agent.service`/`bmi30-tunnel.service`.

## Актуальное задание устройству: отсутствующие группы в портале (12.08.2026)

Через рабочий reverse SSH Hub получает корневую страницу локального портала
размером около 71 KiB. В исходном HTML самой Raspberry отсутствуют данные и
разметка подключённых групп: строк `groups` и `group_state` нет. Hub при
проксировании не удаляет DOM-блоки, поэтому это не потеря данных на центральном
сервере — локальный портал их не формирует.

Нужно провести на Raspberry read-only аудит источников групп и затем исправить
локальный портал, не затрагивая BMI20:

1. Определить, где существующая программа BMI30 хранит состав групп, роли
   Master/Slave, идентификаторы подключённых устройств, состояние связи и
   время последнего ответа. Сначала искать уже существующий runtime/event-cache
   и действующий протокол устройства; не создавать второй независимый источник.
2. Сравнить данные прямого локального открытия `http://127.0.0.1/` и JSON
   `http://127.0.0.1/api/status`. Зафиксировать, какие ожидаемые поля имеются в
   runtime, но не доходят до портала.
3. Добавить в `/api/status` отдельную стабильную структуру `groups`. Например
   (точные имена адаптировать к реально существующей модели устройства):

```json
{
  "groups": [
    {
      "group_id": "<стабильный ID>",
      "name": "<имя группы>",
      "role": "master",
      "members": [
        {
          "device_id": "<ID участника>",
          "name": "<отображаемое имя>",
          "role": "slave",
          "connected": true,
          "last_seen_at": "<ISO-8601 или пустая строка>"
        }
      ]
    }
  ]
}
```

4. Если реальная модель использует не `group_id/name/members`, сохранить её
   смысл без выдуманных данных и описать принятую схему в отчёте. Пустая группа
   должна передаваться как `[]`, ошибка чтения — отдельным безопасным полем, а
   не маскироваться пустым успешным результатом.
5. Добавить на локальную HTML-страницу отдельную карточку **Connected Groups**:
   название/ID группы, роль текущего BMI30, участники, online/offline и последнее
   соединение. Для отсутствующих групп показать `No connected groups`, для
   ошибки — понятный статус ошибки.
6. Проверить остальные уже доступные runtime-данные и перечислить в отчёте всё,
   что было в источнике, но не отображалось в портале. Добавлять только полезные
   диагностические поля без паролей, token, private key и персональных секретов.
7. Все ссылки, формы и API-запросы портала оставить относительными, чтобы они
   работали как локально, так и через
   `/bmi30/device/BMI30-<16_HEX>/`. Не зашивать IP Raspberry или адрес Hub.

Проверка после изменения:

```bash
curl -fsS http://127.0.0.1/api/status | jq '{groups, group_state, sync_mode}'
curl -fsS http://127.0.0.1/ | grep -F 'Connected Groups'
```

Затем проверить ту же страницу через Hub в новой вкладке и приложить в отчёт
результат прямого и проксированного открытия. Если состав отличается, показать
конкретный URL/HTTP status ошибочного запроса и stderr локального портала.

## Результат проверки устройства 12.08.2026

Hub и прямой запрос к локальному API через действующий туннель подтвердили:

- RPI: `2026-08-12-150025`;
- STM32: `1.2.37`;
- группа `RS485 Group (M10)` и участники M10/S03/S04/S07 передаются;
- роль текущего устройства — `slave` (`S07`);
- интерфейсы `eth0`, `wlan0` и `wlan0ap`, их локальные адреса и роли есть в
  `status.interfaces`;
- локальный портал содержит карточку `Connected Groups` и открывается через Hub.

Остался один вопрос к агенту Raspberry: почему верхнее поле check-in
`local_ips` по-прежнему передаётся как пустой массив `[]`, хотя адреса уже есть
в `status.interfaces`? Исправить формирование check-in: динамически передавать
в `local_ips` адреса активных non-loopback интерфейсов (сейчас это
`10.43.0.1`, `192.168.0.153`, `10.42.0.1`), не включая `127.0.0.1` и не
зашивая эти конкретные адреса в код. Полный `status.interfaces` при этом
сохранить без изменений.

### Повторная проверка после обновления Hub

В начале проверки reverse SSH и локальный портал отвечали, но при повторной
проверке `12.08.2026 13:29 UTC` listener `26395` на сервере уже отсутствовал.
Последний check-in был `13:20:44 UTC`. Последний сохранённый `/api/status`
содержит:

- `sync_mode.value: "---"` и `device_responded: false`;
- `groups: []`;
- `groups_error: "Device event cache is stale."`;
- пустой `stm32_firmware_version`, хотя check-in отдельно сохраняет известную
  STM32-версию `1.2.37`.

Это вопрос к Raspberry, а не к Hub. На устройстве проверить и исправить:

```bash
systemctl --no-pager --full status bmi30-agent.service bmi30-tunnel.service
journalctl -u bmi30-agent.service -u bmi30-tunnel.service --since '-30 min' --no-pager
ss -ltnp | grep -E ':(80|8765)\b'
curl -fsS http://127.0.0.1/api/status | jq '{sync_mode, groups, groups_error, raspberry_firmware_version, stm32_firmware_version, interfaces}'
```

Если реальные имена unit отличаются, сначала найти их read-only командой
`systemctl list-unit-files | grep -Ei 'bmi30|tunnel|autossh'` и использовать
фактические имена. После исправления обязательны одновременно:

1. оба BMI30 unit в состоянии `enabled` и `active (running)` после reboot;
2. устойчивый reverse SSH listener назначенного порта;
3. `device_responded: true`, реальная роль и непустые группы в `/api/status`;
4. заполненные RPI/STM32 версии и `local_ips` в очередном check-in.

Коды узлов должны передаваться с префиксом роли: `M` для Master и `S` для
Slave, например `M10`, `S03` и `S07`. Префикс `N`, например `N03`, неверен.
Исправить это в `sync_mode.code`, `groups[].local_device_id` и
`groups[].members[].device_id`. Hub временно исправляет `N` на `M`/`S` при
отображении, если роль однозначно передана, но источник должен сразу выдавать
правильный код.

Не маскировать устаревший event cache как актуальные пустые группы. При stale
состоянии сохранять `groups_error`, а также либо передавать отдельно последние
известные группы с явной отметкой времени/`stale: true`, либо не заменять ими
последний подтверждённый runtime snapshot.

### Изменение локального портала групп

Проверка через Hub показала, что страница Raspberry уже отвечает HTTP 200 и
содержит карточку `Connected Groups`, однако её таблица всё ещё выводит
отдельный столбец `Role`, текст `This device: Slave` и ошибочный код `N03`.
Исправлять это нужно в HTML/JS локального портала на Raspberry: Hub передаёт
эту страницу без изменения её структуры.

При этом фактический `/api/status` уже возвращает правильные `M10`, `S03`,
`S04`, `S07` и роли участников. Следовательно, API и сбор групп переделывать
не нужно: ошибка находится только в функции HTML-отрисовки, которая заменяет
правильный префикс `M`/`S` универсальным `N`.

Требуемый вид карточки `Connected Groups`:

1. Оставить идентификаторы участников `M10`, `S03`, `S04`, `S07`.
2. Удалить отдельный столбец `Role` и текст `This device: Master/Slave`: буква
   `M`/`S` в идентификаторе уже сообщает роль.
3. Оставить полезные столбцы `Device`, `Name`, `State`, `Last connection`.
4. В сетевой части портала убрать loopback `127.0.0.1` и показывать первым,
   более заметно, уникальный Wi-Fi IP, например `wifi 192.168.0.153`.
5. Не зашивать IP и номера участников: брать их из актуальных
   `status.interfaces` и `groups[].members`.

После изменения проверить локально и через Hub:

```bash
curl -fsS http://127.0.0.1/ | grep -F 'Connected Groups'
curl -fsS http://127.0.0.1/ | grep -F '<th>Role</th>' && echo 'ERROR: role column remains'
curl -fsS http://127.0.0.1/api/status | jq '{interfaces, groups}'
```

## Новые устройства не появляются в Hub — проверка на Raspberry

Повторная read-only проверка сервера `12.08.2026 17:33 UTC` показала:

- Hub содержит ровно две уникальные записи: исходную
  `BMI30-ABDD2DBC9775FBAE` и новую `BMI30-30D4ED77AA5CED27`;
- `BMI30-30D4ED77AA5CED27` автоматически зарегистрировалось как `pending`
  `12.08.2026 16:23:34 UTC`, было одобрено администратором в `16:27:14 UTC`,
  но перестало выполнять check-in после `16:54:25 UTC`;
- третьей уникальной записи, в том числе `pending`, в базе нет;
- конфликтов Device ID/SSH-ключей нет;
- за проверенные 90 минут сервер принял 165 запросов строго к
  `/bmi30/api/v1/agent/checkin`, и все они получили HTTP 200;
- пока работали два агента, сервер получал примерно четыре check-in в минуту;
  после остановки нового агента поступает примерно два check-in в минуту, то
  есть сейчас Hub достигает только одна Raspberry.

Это также подтверждает требуемое поведение Hub: первый корректный check-in с
новым уникальным Device ID немедленно создаёт запись `pending`. Сервер не
отклонял новые устройства. Неисправность находится на Raspberry или в её
конфигурации до обращения к Hub.

На **каждой из двух новых Raspberry отдельно** провести read-only проверку и
передать результат без token/private key:

```bash
date -Is
hostname
cat /proc/cpuinfo | sed -n 's/^Serial[[:space:]]*:[[:space:]]*//p'
systemctl list-unit-files | grep -Ei 'bmi30|tunnel|autossh'
systemctl --no-pager --full status bmi30-agent.service bmi30-tunnel.service
systemctl show bmi30-agent.service bmi30-tunnel.service \
  -p Id -p LoadState -p ActiveState -p SubState -p Result \
  -p ExecMainStatus -p NRestarts
journalctl -u bmi30-agent.service -u bmi30-tunnel.service --since '-30 min' --no-pager \
  | grep -Ev 'api_token|Authorization|PRIVATE KEY'
getent ahosts www.teiots.net
curl -fsS -o /dev/null -w 'health HTTP %{http_code}\n' \
  https://www.teiots.net/bmi30/health
```

Если unit называются иначе, использовать найденные фактические имена. Затем
найти конфигурацию агента, но вывести только безопасные поля:

```bash
grep -RInE 'device_id|checkin|server_url|hub_url|www\.teiots\.net|65\.21\.225\.43' \
  /etc /opt /home 2>/dev/null \
  | grep -Ev 'api_token|Authorization|private|secret|password' \
  | head -n 200
```

Обязательные условия для отдельной регистрации:

1. URL строго `https://www.teiots.net/bmi30/api/v1/agent/checkin`, не личный
   сервер `65.21.225.43` и не корень `/api/v1/...`.
2. Device ID построен из фактического серийного номера именно этой Raspberry и
   отличается от обеих зарегистрированных записей:
   `BMI30-ABDD2DBC9775FBAE` и `BMI30-30D4ED77AA5CED27`.
3. Каждая Raspberry имеет собственные SSH private/public key и API-token. Не
   копировать файлы идентичности с другого устройства.
4. В журнале агента должен быть виден HTTP-ответ Hub. При HTTP 200/pending
   устройство немедленно появляется в административном списке для подтверждения.
5. Агент должен оставаться `active (running)` и продолжать check-in после
   первого ответа; устройство `BMI30-30D4ED77AA5CED27` сейчас нарушает именно
   это условие.

Ничего не удалять и не пересоздавать до сравнения безопасных Device ID,
серийного номера, URL и статуса unit. Если обнаружено клонирование, сначала
сделать резервную копию файлов идентичности и только затем сгенерировать
отдельную идентичность по процедуре установки агента.

## Обработка ответа

- HTTP 200, `state=pending`: сохранить состояние, туннель не запускать, повторять check-in через `next_checkin_seconds`. Администратор должен подтвердить устройство в Hub.

В общей таблице сайта эти значения отображаются раздельно как `RPI: <agent_version>` и `STM32: <firmware_version>`. Не подставлять одну версию вместо другой: если версия пока неизвестна, передавать пустую строку.
- HTTP 200, `state=approved`: проверить все поля ниже и запустить/обновить tunnel service.
- `blocked` или `rejected`: остановить только BMI30 tunnel и продолжать редкие check-in; BMI20 не трогать.
- HTTP 401/409: не пересоздавать ключ или token автоматически. Записать обезличенную ошибку и остановить цикл быстрых повторов.
- 5xx/timeout: exponential backoff с верхним пределом; действующий туннель не уничтожать из-за одного сбоя.

Поля approved:

```json
{
  "remote_port": 20000,
  "listen_address": "0.0.0.0",
  "ssh_host": "www.teiots.net",
  "ssh_port": 2222,
  "ssh_user": "bmi30-tunnel",
  "ssh_host_public_key": "ssh-ed25519 AAAA..."
}
```

Принимать `remote_port` только в диапазоне 20000–39999, `ssh_port` только 2222, `ssh_user` только `bmi30-tunnel`, host только `www.teiots.net`, а ключ сервера только Ed25519.

## Закрепление SSH host key

Approved-ответ получен по HTTPS с доверенным сертификатом, поэтому его `ssh_host_public_key` можно использовать для первичного pinning. Создать отдельный known-hosts файл со строкой:

```text
[www.teiots.net]:2222 ssh-ed25519 AAAA...
```

Использовать `StrictHostKeyChecking=yes` и отдельный `UserKnownHostsFile`. При изменении уже закреплённого ключа туннель не запускать и не принимать новый ключ автоматически.

## Reverse SSH

После локального определения HTTP-порта команда должна быть эквивалентна:

```bash
ssh -NT \
  -i /etc/bmi30-agent/id_ed25519 \
  -o BatchMode=yes \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile=/etc/bmi30-agent/known_hosts \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -p 2222 \
  -R 0.0.0.0:<REMOTE_PORT>:127.0.0.1:<LOCAL_HTTP_PORT> \
  bmi30-tunnel@www.teiots.net
```

Не открывать `<REMOTE_PORT>` в firewall Raspberry и не добавлять password authentication. Сервер ограничивает ключ одним назначенным remote port; другие порты должны отклоняться.

## systemd и проверка

- Запускать агент и туннель от отдельного минимально привилегированного пользователя, если доступ к локальному приложению это позволяет.
- Использовать `Restart=on-failure`, разумный `RestartSec`, hardening systemd и отдельный EnvironmentFile без вывода секретов.
- До включения autostart проверить: check-in pending, подтверждение в Hub, approved-ответ, успешный SSH tunnel, открытие локального UI через Hub.
- После `systemctl enable` перезагрузить Raspberry и повторить все проверки.
- Финальный отчёт должен содержать имена созданных файлов/units, контрольные суммы, статусы services, последние обезличенные строки журналов и точную команду rollback. Не включать private key, API token или пароли.
