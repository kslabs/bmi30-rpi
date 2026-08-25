# Задание для ChatGPT/Codex на сервере BMI30 Tunnel Hub

Скопируйте весь текст ниже в задачу агенту, запущенному непосредственно на
сервере `65.21.225.43` с правами администратора.

```text
Нужно настроить этот сервер как BMI30 Tunnel Hub для исходящих reverse-SSH
туннелей от устройств. Работай до проверенного результата, но не отключай и не
перенастраивай существующие службы без предварительной read-only проверки.

Известно снаружи на 2026-08-03:
- публичный IPv4: 65.21.225.43;
- HTTP/80 отвечает 404 с Server: Microsoft-HTTPAPI/2.0;
- TCP/22 не отдает SSH host key;
- HTTPS/443 не отвечает;
- BMI30 будут подключаться командой примерно:
  ssh -NT -R 0.0.0.0:REMOTE_PORT:127.0.0.1:80 bmi30-tunnel@65.21.225.43;
- REMOTE_PORT каждого устройства находится строго в диапазоне 20000..39999;
- пока дополнительная авторизация на публичной странице и tunnel-портах не
  нужна. Не удаляй существующую авторизацию самого BMI30 Portal.

Сначала определи ОС, текущего владельца HTTP/80, правила host/cloud firewall,
наличие OpenSSH Server, Python/.NET и механизм автозапуска. Выведи результаты.
HTTP banner похож на Windows; если это Windows, используй штатный OpenSSH Server
и Windows Service. Если ОС другая, реализуй эквивалент через systemd/OpenSSH.

Настрой прием reverse SSH:
1. Установи и запусти OpenSSH Server, включи автозапуск.
2. Открой входящий TCP/22 и проверь доступность с внешнего адреса. Учитывай как
   локальный firewall, так и firewall/ACL хостинг-провайдера.
3. Создай отдельного непривилегированного пользователя `bmi30-tunnel`, без
   административных групп. Парольный SSH-вход для него отключи; только ключи.
4. Разреши ему только remote TCP forwarding. Настрой `GatewayPorts
   clientspecified`, чтобы запрошенный адрес 0.0.0.0 был публичным. Запрети PTY,
   agent/X11 forwarding и обычные команды настолько, насколько это совместимо
   с `ssh -N` на установленной версии OpenSSH.
5. Не добавляй общий приватный ключ. У каждого BMI30 будет уникальная пара
   ключей. Для каждого enrollment агент получит DEVICE_ID, REMOTE_PORT и
   PUBLIC_KEY. Добавляй ключ отдельной строкой authorized_keys с ограничениями:
   restrict,port-forwarding,permitlisten="0.0.0.0:REMOTE_PORT"
   Перед применением проверь синтаксис фактически установленного OpenSSH.
6. Открой публичный TCP-диапазон 20000..39999. Не открывай UDP. Проверь, что
   незанятые порты ничего не отдают, а активный remote forward доступен извне.

Сделай открытый dashboard всех BMI30:
1. Не занимай и не ломай текущий HTTP/80. Подними отдельную службу на TCP/8080,
   если безопасно встроиться в существующий HTTP listener нельзя.
2. Dashboard должен автоматически получать список активных TCP listeners в
   диапазоне 20000..39999, а не сканировать все 20000 портов по сети.
3. Для каждого реально слушающего tunnel-порта запроси только локальный адрес
   `http://127.0.0.1:PORT/api/status` с timeout не более 1 секунды. Из JSON покажи
   hostname, firmware version, tunnel port, online/last seen и ссылку
   `http://65.21.225.43:PORT/`.
4. Храни небольшой known_devices.json, чтобы недавно отключившиеся устройства
   оставались в списке как Offline. Атомарно записывай файл.
5. Не принимай произвольный target/port из HTTP query: источником портов должны
   быть только локальные listener-сокеты допустимого диапазона. Экранируй HTML.
6. Страница и JSON API сейчас без дополнительного пароля. Явно пометь в UI
   `Temporary public access`. Открой TCP/8080 и установи службу в автозапуск.

Проверка и отчет:
- проверь конфигурацию sshd до restart и сохрани backup измененных конфигов;
- покажи status OpenSSH и dashboard service;
- покажи listening ports 22 и 8080;
- выведи публичные SSH host-key fingerprints SHA256 для сверки на BMI30;
- создай файл отчета с путями конфигов, firewall rules, URL dashboard,
  процедурой добавления/отзыва одного device key и полным rollback;
- не выводи приватные ключи и пароли;
- если внешний cloud firewall нельзя изменить с сервера, точно перечисли порты
  TCP 22, 8080, 20000-39999, которые владелец должен разрешить вручную;
- остановись перед enrollment только если еще не переданы PUBLIC_KEY и
  REMOTE_PORT: серверная база, firewall и dashboard должны быть уже готовы.
```

## Enrollment первого BMI30

Эти данные уже созданы на устройстве `BMI30-ABDD2DBC9775FBAE`; приватный ключ
остался только на самом BMI30:

```text
DEVICE_ID=BMI30-ABDD2DBC9775FBAE
REMOTE_PORT=29476
PUBLIC_URL=http://65.21.225.43:29476/
PUBLIC_KEY=ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICSBzvBGwcJhWvoz8ZDOrWDC6Bz1/o3lo0JYvD0MT58X BMI30-ABDD2DBC9775FBAE@bmi30-tunnel
```

Строка для `authorized_keys` пользователя `bmi30-tunnel` после проверки
поддерживаемого синтаксиса установленного OpenSSH:

```text
restrict,port-forwarding,permitlisten="0.0.0.0:29476" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAICSBzvBGwcJhWvoz8ZDOrWDC6Bz1/o3lo0JYvD0MT58X BMI30-ABDD2DBC9775FBAE@bmi30-tunnel
```

## Подготовка каждого BMI30

После готовности серверной части на каждом устройстве сначала создайте
уникальный enrollment без запуска службы:

```bash
cd /home/techaid/Documents
sudo ./utilities/install_bmi30_reverse_tunnel.sh
```

Передайте серверному агенту напечатанные `DEVICE_ID`, `REMOTE_PORT` и
`PUBLIC_KEY`. После добавления ключа на сервере сравните показанный серверным
агентом SHA256 fingerprint и включите туннель:

```bash
sudo ./utilities/install_bmi30_reverse_tunnel.sh --scan-host-key --enable
```

Проверка устройства:

```bash
systemctl --no-pager --full status bmi30-reverse-tunnel.service
```

Закрытый ключ создается только локально в
`/home/techaid/.ssh/id_ed25519_bmi30_tunnel` и не входит в firmware/cloud
archive. Удаление службы сохраняет ключ для безопасного повторного enrollment:

```bash
sudo ./utilities/install_bmi30_reverse_tunnel.sh --remove
```
