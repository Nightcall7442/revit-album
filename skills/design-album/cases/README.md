# Эталонные проекты (регрессия)

Каждая папка: `project.json` + `expected.json`. `tests/test_regression.py` собирает их целиком и требует 0 ошибок и
неизменных ключевых чисел. Добавляет эталоны скилл improve-agent после сдачи проекта (данные заказчика — обезличить).

`expected.json`:
```json
{"sheets": 19, "plan_scale": 50, "total_area": 46.00, "accepted_data_warnings": ["DOORS_CLASH"],
 "max_sheet_warnings": 35, "titles": ["Обмерный план", "План освещения"]}
```
