# -*- coding: utf-8 -*-
"""
Сборка zip для Chrome Web Store.

Запуск: python build_zip.py  (из корня репозитория)
Результат: dist/BlatTabs-<версия>.zip

Состав zip строго задан списком FILES ниже — в архив попадают ТОЛЬКО файлы
расширения (manifest, скрипты, html, css, иконки). Всё остальное в корне
(test_plugin.py, .pytest_cache, __pycache__, .git, *.md, dist/, и т.п.)
исключается.

Определённость: файлы идут в порядке списка, у каждого архивного элемента
зафиксирована дата/время (FIXED_DATE), поэтому одинаковый вход даёт
байт-в-байт одинаковый zip.
"""
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))

# Фиксированная дата архивного элемента (2020-01-01) — для воспроизводимости
FIXED_DATE = (2020, 1, 1, 0, 0, 0)


def read_version():
    """Версия из manifest.json — используется в имени zip."""
    with open(os.path.join(ROOT, "manifest.json"), "r", encoding="utf-8") as f:
        return json.load(f)["version"]


def build_files():
    """Точный список файлов расширения (относительно корня), в порядке записи."""
    return [
        "manifest.json",
        "background.js",
        "popup.html",
        "popup.js",
        "view.html",
        "view.js",
        "theme.css",
        "icons/icon16.png",
        "icons/icon48.png",
        "icons/icon128.png",
    ]


def main():
    version = read_version()
    files = build_files()

    # Проверяем, что все файлы существуют перед сборкой
    missing = [f for f in files if not os.path.isfile(os.path.join(ROOT, f))]
    if missing:
        sys.exit("Нет файлов: " + ", ".join(missing))

    dist_dir = os.path.join(ROOT, "dist")
    os.makedirs(dist_dir, exist_ok=True)
    out_path = os.path.join(dist_dir, "BlatTabs-v%s.zip" % version)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for rel in files:
            full = os.path.join(ROOT, *rel.split("/"))
            # Arcname использует "/" (POSIX-разделитель), как требует zip-формат
            arcname = rel.replace(os.sep, "/")
            # Зафиксированная дата у элемента — для воспроизводимости сборки
            info = zipfile.ZipInfo(arcname, date_time=FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16  # обычный файл, без Windows-флагов
            with open(full, "rb") as f:
                zf.writestr(info, f.read())

    print("Собрано: %s" % out_path)
    with zipfile.ZipFile(out_path, "r") as zf:
        for info in zf.infolist():
            print("  %s  (%d bytes)" % (info.filename, info.file_size))


if __name__ == "__main__":
    main()
