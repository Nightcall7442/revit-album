# Space Design Album — плагин для Claude

Агент делает альбом дизайн-проекта интерьера (как CoffeeCity / Ургенч, Space Design Studio) из 3D-сцены 3ds Max,
DWG/DXF или PDF/фото обмера и, по запросу, модель Revit.

## Как пользоваться
- `/album <файл или папка>` — альбом одной командой из .max, DWG/DXF, PDF, фото или project.json. Агент сам
  исправит шум данных, предложит по нормам свет, розетки, сантехнику, полы и потолки (помечая это как предложение),
  соберёт PDF + DXF, проверит листы и перечислит вопросы к заказчику.
- `/album-edit <что изменить>` — правка словами: «розетку у кровати выше на 300», «переименуй спальню».
  Каждая правка в журнале: откат и список изменений для заказчика.
- `/album-revit` — модель и все листы для Revit (Dynamo / pyRevit).
- `/album-learn <замечание>` — научить агента на ошибке: тест, исправление движка, урок, новая версия плагина.
Можно и просто словами: «Сделай дизайн-проект по сцене …max», «Перенеси в Revit», «Улучши агента: …».

## Состав
- `skills/design-album/` — инструкции, справочники (`references/`), движок (`scripts/sdalbum`), импорт
  (`scripts/importers`), тесты (`scripts/tests`), эталоны (`examples/`, `cases/`), шрифт и логотип (`assets/`).
- `skills/improve-agent/` — процедура развития агента.
- `commands/` — команды `/album`, `/album-edit`, `/album-revit`, `/album-learn`.

## Проверка вручную
```
cd skills/design-album/scripts
python3 sda.py doctor
python3 sda.py test          # все тесты, ~3 мин
python3 sda.py make ../examples/urgench-apartment/project.json /tmp/out
```

## Лицензии
Движок — Space Design Studio. `scripts/importers/max_lib/import_max.py` — GPL-2.0-or-later (проект io_scene_max).
Шрифт Inter — SIL OFL 1.1 (`assets/fonts/OFL.txt`).

## Дом агента в облаке (Railway)

Репозиторий — это и плагин Claude, и веб-сервис. `Dockerfile` + `railway.toml` разворачивают `server/app.py`:
страница с загрузкой исходника (.max, DWG/DXF, PDF, фото, project.json, .zip) → альбом PDF/DXF, отчёт и
project.json; очередь сборок (по одной: сцена 3ds Max берёт до ~8 ГБ памяти); результаты — на томе `/data`;
`/plugin` — скачать плагин этой версии. Переменные: `ACCESS_TOKEN` (пароль страницы, логин любой), `DATA_DIR`.
