import csv
from pathlib import Path

import pandas as pd

csv.field_size_limit(10_000_000)

RAW_PATH = Path("data/raw/apartments_for_rent_classified_100K.csv")
CLEAN_PATH = Path("data/processed/apartments_clean.csv")

# 1. Загружаем исходные данные
with RAW_PATH.open(encoding="cp1252", newline="") as f:
    reader = csv.reader(f, delimiter=";")
    columns = next(reader)
    df = pd.DataFrame(reader, columns=columns)

print("Исходных объявлений:", len(df))

# 2. Обозначаем пустые значения как пропуски
df = df.replace("", pd.NA)

# 3. Преобразуем числовые столбцы
numeric_columns = [
    "price",
    "square_feet",
    "bedrooms",
    "bathrooms",
    "latitude",
    "longitude",
]

for col in numeric_columns:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# 4. Удаляем полные дубликаты
df = df.drop_duplicates()
print("После удаления дубликатов:", len(df))

# 5. Оставляем только месячную аренду в долларах
df = df[(df["price_type"] == "Monthly") & (df["currency"] == "USD")].copy()

print("После фильтрации аренды:", len(df))

# 6. Удаляем записи без цены или площади
df = df.dropna(subset=["price", "square_feet"])

# 7. Удаляем некорректные нулевые и отрицательные значения
df = df[(df["price"] > 0) & (df["square_feet"] > 0)].copy()

print("После проверки цены и площади:", len(df))

# Исключаем записи по результатам ручной проверки описаний.
# Используем ID объявлений: номера строк могут измениться.
exclusion_reasons = {
    "5666447277": "Цена противоречит описанию; площадь также подозрительна",
    "5668662559": "Указана площадь спортивного клуба вместо квартиры",
    "5411249530": "Сомнительная площадь; корректное значение не подтверждено",
    "5315021593": "Указана площадь парка на крыше вместо квартиры",
}

excluded_mask = df["id"].astype(str).isin(exclusion_reasons)

# Сохраняем исключённые записи и причины в отдельный отчёт.
excluded = df.loc[excluded_mask].copy()
excluded["exclusion_reason"] = excluded["id"].astype(str).map(exclusion_reasons)

report_path = Path("reports/excluded_records.csv")
report_path.parent.mkdir(parents=True, exist_ok=True)

excluded[["id", "title", "price", "square_feet", "exclusion_reason"]].to_csv(
    report_path, index=False, encoding="utf-8"
)

# Убираем эти записи из обучающего датасета.
df = df.loc[~excluded_mask].copy()

print("Исключено после ручной проверки:", len(excluded))
print("Отчёт об исключениях:", report_path)

# 8. Сохраняем очищенный датасет
CLEAN_PATH.parent.mkdir(parents=True, exist_ok=True)

df.to_csv(CLEAN_PATH, index=False, encoding="utf-8")

print("\nОЧИСТКА ЗАВЕРШЕНА")
print("Итоговое количество квартир:", len(df))
print("Количество колонок:", len(df.columns))
print("Файл сохранён:", CLEAN_PATH)
