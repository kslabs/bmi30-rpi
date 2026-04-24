# Hotspot Info Page

После запуска:

sudo ./install_bmi30_network_identity.sh

на устройстве устанавливается локальная web-страница статуса hotspot.

Что появляется:

1. HTTP-сервис на порту 80.
2. Страница с текущими IPv4-адресами устройства.
3. Подсказки для SSH и RDP.
4. JSON endpoint: /api/status.

Основной адрес:

http://10.42.0.1/

Отдельно для прямого подключения ПК по Ethernet:

1. Запустите sudo ./utilities/setup_ethernet_portal.sh install
2. После этого Raspberry Pi будет раздавать IP по eth0.
3. Адрес portal mode по кабелю по умолчанию: http://10.43.0.1/

Что показывает страница:

1. SSID hotspot.
2. IP hotspot.
3. Wi-Fi IP.
4. Ethernet IP.
5. Команду для SSH.
6. Адрес для RDP.

Автооткрытие страницы:

Скрипт добавляет DNS-переадресацию для типовых captive-portal probe доменов:

1. Android / ChromeOS
2. Windows NCSI
3. Apple Captive Portal
4. Firefox detectportal
5. GNOME connectivity check

Это не гарантирует popup на каждом устройстве, но на многих телефонах и ноутбуках страница будет показываться автоматически после подключения к hotspot.

Если popup не появился:

1. Откройте вручную http://10.42.0.1/
2. Или http://10.42.0.1/api/status

Systemd unit:

1. bmi30-hotspot-info.service

Файлы установки в системе:

1. /usr/local/bin/bmi30-hotspot-info-server.py
2. /etc/systemd/system/bmi30-hotspot-info.service
3. /etc/NetworkManager/dnsmasq-shared.d/90-bmi30-hotspot-portal.conf