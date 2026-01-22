#!/bin/bash
# Запуск BMI30.200.py с фильтрацией вывода - показываем только CAPTURE логи и ошибки

cd /home/techaid/Documents

# Отключаем отладочный вывод USB reader
export BMI30_READER_DEBUG=0

# Запускаем программу и фильтруем вывод
/home/techaid/Documents/.usbvenv/bin/python host/BMI30.200.py 2>&1 | \
  grep --line-buffered -E '\[CAPTURE\]|CAPTURE|Автозахват|Error|ERROR|Traceback|Exception' | \
  grep -v "Error recording frame"
