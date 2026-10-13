---
description: Перенос альбома в Revit — модель (стены, окна, двери, помещения) и все листы
argument-hint: [папка на компьютере пользователя]
---

Подготовь альбом для Revit. $ARGUMENTS

Скилл **design-album**, `references/revit.md`.

1. `python3 sda.py make work/<объект>/project.json work/<объект> --revit --target-dir "<папка на ПК>"` — в
   `work/<объект>/revit/` появятся `.dyn` (Dynamo: PythonNet3 для Revit 2025+, CPython3 для 2022–2024),
   `revit_build_model.py` (pyRevit) и листы `ДП_NN.dxf` с картинками.
2. Если компьютер пользователя подключён — запиши пакет в указанную папку; если нет — отправь файлы и
   инструкцию из `revit.md` (Revit → новый проект → Управление → Dynamo → открыть .dyn → Запуск).
3. Действовать в Revit на ПК пользователя — только с его явного разрешения.
