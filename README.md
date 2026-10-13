# Space Design Album — плагин для Claude

Агент делает альбом дизайн-проекта интерьера (как CoffeeCity / Ургенч, Space Design Studio) из 3D-сцены 3ds Max,
DWG/DXF или PDF/фото обмера и, по запросу, модель Revit.

## Как пользоваться
Попросите Claude: «Сделай дизайн-проект по сцене …max» / «Альбом рабочих чертежей по этому DWG» / «Перенеси в Revit».
Скилл **design-album** ведёт работу: импорт → project.json → проверка данных → сборка → проверка листов → приёмка
глазами → PDF + DXF (+ Revit). Нашли ошибку агента — скажите «улучши агента: …» — скилл **improve-agent** добавит тест,
исправит движок, запишет урок и выпустит новую версию плагина.

## Состав
- `skills/design-album/` — инструкции, справочники (`references/`), движок (`scripts/sdalbum`), импорт
  (`scripts/importers`), тесты (`scripts/tests`), эталоны (`examples/`, `cases/`), шрифт и логотип (`assets/`).
- `skills/improve-agent/` — процедура развития агента.

## Проверка вручную
```
cd skills/design-album/scripts
python3 sda.py doctor
python3 sda.py test          # все тесты, ~2 мин
python3 sda.py build ../examples/urgench-apartment/project.json /tmp/out --png
```

## Лицензии
Движок — Space Design Studio. `scripts/importers/max_lib/import_max.py` — GPL-2.0-or-later (проект io_scene_max).
Шрифт Inter — SIL OFL 1.1 (`assets/fonts/OFL.txt`).
