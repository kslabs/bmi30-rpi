#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
WORKSPACE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

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

show_menu() {
    printf "\nBMI30 Utilities Menu\n"
    printf "===================\n"
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
    printf "12. Сделать бэкап сейчас (вручную)\n"
    printf "13. Включить авто-бэкап ежедневно в 23:00\n"
    printf "14. Проверить статус бэкапа\n"
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
            run_action "Облачный бэкап проекта" bash "$SCRIPT_DIR/backup_to_cloud.sh"
            ;;
        13)
            run_action "Установка авто-бэкапа (23:00 каждый день)" bash "$SCRIPT_DIR/backup_to_cloud.sh" --install-timer --on-calendar "*-*-* 23:00:00"
            ;;
        14)
            run_action "Статус бэкапа" bash "$SCRIPT_DIR/backup_status.sh"
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
