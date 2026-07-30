#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BMI30_CORE_SERVICE="${BMI30_CORE_SERVICE:-bmi30-core.service}"

pause_menu() {
    printf "\nНажмите Enter, чтобы вернуться в меню..."
    read -r _
}

run_action() {
    local title="$1"
    shift

    printf "\n=== %s ===\n\n" "$title"
    if (cd "$WORKSPACE_DIR" && "$@"); then
        printf "\nГотово.\n"
    else
        local status=$?
        printf "\nКоманда завершилась с кодом %d.\n" "$status"
    fi
}

bmi30_core_state_text() {
    if ! command -v systemctl >/dev/null 2>&1; then
        printf "systemctl недоступен"
        return 0
    fi

    local state
    state="$(systemctl is-active "$BMI30_CORE_SERVICE" 2>&1 || true)"
    case "$state" in
        *"Failed to connect"*|*"System has not been booted"*|*"Host is down"*)
            printf "systemd недоступен"
            ;;
        active)
            printf "запущено"
            ;;
        inactive)
            printf "остановлено"
            ;;
        activating)
            printf "запускается"
            ;;
        deactivating)
            printf "останавливается"
            ;;
        failed)
            printf "ошибка"
            ;;
        unknown|"")
            if systemctl cat "$BMI30_CORE_SERVICE" >/dev/null 2>&1; then
                printf "неизвестно"
            else
                printf "сервис не найден"
            fi
            ;;
        *)
            printf "%s" "$state"
            ;;
    esac
}

bmi30_core_enabled_text() {
    if ! command -v systemctl >/dev/null 2>&1; then
        return 0
    fi

    local enabled
    enabled="$(systemctl is-enabled "$BMI30_CORE_SERVICE" 2>/dev/null || true)"
    case "$enabled" in
        enabled)
            printf "автозапуск включен"
            ;;
        disabled)
            printf "автозапуск выключен"
            ;;
        static|generated|indirect|alias)
            printf "%s" "$enabled"
            ;;
        ""|not-found|*"Failed to connect"*|*"System has not been booted"*|*"Host is down"*)
            ;;
        *)
            printf "%s" "$enabled"
            ;;
    esac
}

show_bmi30_core_status() {
    local state_text enabled_text
    state_text="$(bmi30_core_state_text)"
    enabled_text="$(bmi30_core_enabled_text)"

    printf "BMI30 split-система: %s" "$state_text"
    if [[ -n "$enabled_text" ]]; then
        printf " / %s" "$enabled_text"
    fi
    printf " (%s)\n" "$BMI30_CORE_SERVICE"
}

run_core_service_action() {
    local title="$1"
    local action="$2"

    run_action "$title" sudo systemctl "$action" "$BMI30_CORE_SERVICE"
    printf "\n"
    show_bmi30_core_status
}

show_core_service_details() {
    show_bmi30_core_status
    printf "\n"

    if ! command -v systemctl >/dev/null 2>&1; then
        return 0
    fi

    systemctl --no-pager --full status "$BMI30_CORE_SERVICE" || true
}

show_menu() {
    printf "\nBMI30 Utilities Menu\n"
    printf "===================\n"
    show_bmi30_core_status
    printf "\n"
    printf "1. Проверить источник загрузки\n"
    printf "2. Проверить BOOT_ORDER загрузчика\n"
    printf "3. Сделать USB приоритетом загрузки\n"
    printf "4. Полное копирование USB -> eMMC\n"
    printf "5. Синхронизировать изменения USB -> eMMC\n"
    printf "6. Полное копирование eMMC -> USB\n"
    printf "7. Синхронизировать изменения eMMC -> USB\n"
    printf "8. Обновить уникальное имя по серийному номеру\n"
    printf "9. Включить Ethernet portal mode\n"
    printf "10. Показать список утилит\n"
    printf "11. Открыть README утилит\n"
    printf "12. Задеплоить hotspot_info_server.py (обновить страницу)\n"
    printf "13. Опубликовать текущую прошивку в облако\n"
    printf "14. Меню версий BMI30 split-системы\n"
    printf "15. Запустить BMI30 split-систему\n"
    printf "16. Остановить BMI30 split-систему\n"
    printf "17. Проверить и установить последнюю прошивку из облака\n"
    printf "18. Принудительно переустановить последнюю прошивку из облака\n"
    printf "19. Показать подробный статус BMI30 split-системы\n"
    printf "20. Проверить статус cloud sync\n"
    printf "0. Выход\n"
}

while true; do
    show_menu
    printf "\nВыберите действие: "
    read -r choice

    case "$choice" in
        1)
            run_action "Проверка источника загрузки" bash "$SCRIPT_DIR/check_boot_source.sh"
            ;;
        2)
            run_action "Проверка BOOT_ORDER" bash "$SCRIPT_DIR/check_bootloader.sh"
            ;;
        3)
            run_action "USB-first в BOOT_ORDER" sudo bash "$SCRIPT_DIR/set_usb_boot_priority.sh"
            ;;
        4)
            run_action "Полное копирование USB -> eMMC" sudo bash "$SCRIPT_DIR/migrate_system_to_emmc.sh"
            ;;
        5)
            run_action "Синхронизация изменений USB -> eMMC" sudo bash "$SCRIPT_DIR/sync_system_to_emmc.sh"
            ;;
        6)
            run_action "Полное копирование eMMC -> USB" sudo bash "$SCRIPT_DIR/migrate_system_to_usb.sh"
            ;;
        7)
            run_action "Синхронизация изменений eMMC -> USB" sudo bash "$SCRIPT_DIR/sync_system_to_usb.sh"
            ;;
        8)
            run_action "Обновление уникального имени" sudo bash "$SCRIPT_DIR/refresh_network_identity.sh"
            ;;
        9)
            run_action "Настройка Ethernet portal mode" sudo bash "$SCRIPT_DIR/setup_ethernet_portal.sh" install
            ;;
        10)
            run_action "Список утилит" bash "$SCRIPT_DIR/list_tools.sh"
            ;;
        11)
            run_action "README утилит" sed -n '1,260p' "$SCRIPT_DIR/README.md"
            ;;
        12)
            run_action "Деплой hotspot_info_server.py" sudo env BMI30_PORTAL_SRC="$WORKSPACE_DIR/hotspot_info_server.py" bash -c '
                set -euo pipefail
                src="$BMI30_PORTAL_SRC"
                dst="/usr/local/bin/bmi30-hotspot-info-server.py"
                start_ts="$(date +%s)"
                install -m 755 "$src" "$dst"
                end_ts="$(date +%s)"
                elapsed_s=$((end_ts - start_ts))
                if (( elapsed_s <= 0 )); then
                    elapsed_s=1
                fi
                bytes="$(stat -c "%s" "$dst" 2>/dev/null || printf "0")"
                [[ "$bytes" =~ ^[0-9]+$ ]] || bytes=0
                rate=$((bytes / elapsed_s))
                size="$(numfmt --to=iec --suffix=B "$bytes" 2>/dev/null || printf "%sB" "$bytes")"
                speed="$(numfmt --to=iec --suffix=B/s "$rate" 2>/dev/null || printf "%sB/s" "$rate")"
                printf "Copy: duration %ss, average speed %s, size %s\n" "$elapsed_s" "$speed" "$size"
                systemctl restart bmi30-hotspot-info.service
                printf "OK: строк: %s\n" "$(wc -l < "$dst")"
            '
            ;;
        13)
            run_action "Публикация текущей прошивки в облако" bash "$SCRIPT_DIR/backup_to_cloud.sh" --force
            ;;
        14)
            run_action "Меню версий BMI30 split-системы" bash "$WORKSPACE_DIR/switch_bmi30_split_versions.sh"
            ;;
        15)
            run_core_service_action "Запуск BMI30 split-системы" start
            ;;
        16)
            run_core_service_action "Остановка BMI30 split-системы" stop
            ;;
        17)
            run_action "Установка последней прошивки из облака" bash "$SCRIPT_DIR/cloud_sync_now.sh" --today-only
            ;;
        18)
            run_action "Принудительная переустановка последней прошивки из облака" bash "$SCRIPT_DIR/update_from_cloud.sh" --force
            ;;
        19)
            run_action "Статус BMI30 split-системы" show_core_service_details
            ;;
        20)
            run_action "Статус backup" bash "$SCRIPT_DIR/backup_status.sh"
            ;;
        0|q|Q|exit)
            exit 0
            ;;
        *)
            printf "\nНеизвестный пункт меню.\n"
            ;;
    esac

    pause_menu
done
