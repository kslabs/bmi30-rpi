import os
import re

def increment_version(version):
    return f"{int(version) + 1:03d}"

def copy_and_update_version(file_path, old_version, new_version):
    with open(file_path, 'r') as file:
        content = file.read()

    # Обновляем версию в содержимом файла
    new_content = re.sub(r'version = \d+\.\d+', f'version = {int(new_version):d}.00', content)

    # Обновляем номер версии в названии файла
    new_file_path = file_path.replace(old_version, new_version)

    with open(new_file_path, 'w') as new_file:
        new_file.write(new_content)

    print(f"Created new version: {new_file_path}")

# Укажите текущую версию и файлы для обновления
old_version = "005"
new_version = increment_version(old_version)
files_to_update = [
    "/home/techaid/Documents/BMI30.005.py",
    "/home/techaid/Documents/bmi30_def.py"
]

for file_path in files_to_update:
    copy_and_update_version(file_path, old_version, new_version)
