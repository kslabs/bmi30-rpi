"""
usb_cdc_receiver.py — облегчённая обёртка

Этот файл делегирует запуск модульному USB_receiver.main().
Так мы избегаем дублирования и сокращаем размер.
"""
from __future__ import annotations
import sys


def main() -> int:
    try:
        import USB_receiver  # type: ignore
    except Exception as e:
        print(f"Не удалось импортировать USB_receiver: {e}")
        return 2
    try:
        # Делегируем и нормализуем код возврата
        ret = USB_receiver.main()  # type: ignore[attr-defined]
        try:
            return int(ret)
        except Exception:
            return 0
    except SystemExit as ex:
        try:
            return int(ex.code) if ex.code is not None else 0
        except Exception:
            return 0
    except Exception as e:
        print(f"usb_cdc_receiver wrapper error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())