import csv

import pandas as pd

# Увеличиваем лимит для длинных текстовых полей
csv.field_size_limit(10_000_000)

# Путь к исходному датасету
DATA_PATH = "data/raw/apartments_for_rent_classified_100K.csv"

# Загружаем CSV через стандартный модуль csv
with open(DATA_PATH, encoding="cp1252", newline="") as f:
    reader = csv.reader(f, delimiter=";")
    columns = next(reader)
    df = pd.DataFrame(reader, columns=columns)

# Пустые значения преобразуем в пропуски
df = df.replace("", pd.NA)

# Преобразуем числовые столбцы
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

# 1. Размер датасета
print("РАЗМЕР ДАТАСЕТА")
print("Количество квартир:", df.shape[0])
print("Количество колонок:", df.shape[1])

# 2. Типы данных
print("\nТИПЫ ДАННЫХ")
print(df.dtypes)

# 3. Пропущенные значения
print("\nПРОПУСКИ")
print(df.isna().sum().sort_values(ascending=False))

# 4. Дубликаты объявлений
print("\nДУБЛИКАТЫ ПО ID")
print(df["id"].duplicated().sum())

# 5. Типы оплаты аренды
print("\nТИПЫ ОПЛАТЫ")
print(df["price_type"].value_counts(dropna=False))

# 6. Основные характеристики
print("\nСТАТИСТИКА ЦЕНЫ И ПЛОЩАДИ")
print(df[["price", "square_feet"]].describe())

# 7. Подробная статистика цены и площади
print("\nПРОЦЕНТИЛИ ЦЕНЫ И ПЛОЩАДИ")

print(df[["price", "square_feet"]].quantile([0.01, 0.50, 0.95, 0.99, 0.999]))

# 8. Проверка подозрительных значений
print("\nПОТЕНЦИАЛЬНЫЕ ВЫБРОСЫ")

print("Цена выше $10 000:", (df["price"] > 10000).sum())
print("Цена ниже $300:", (df["price"] < 300).sum())

print("Площадь больше 5 000 ft²:", (df["square_feet"] > 5000).sum())

print("Площадь меньше 200 ft²:", (df["square_feet"] < 200).sum())

# 9. Проверка повторяющихся объявлений
print("\nДИНАМИКА ДУБЛИКАТОВ")

print("Повторяющиеся ID:", df["id"].duplicated().sum())
print("Полностью одинаковые строки:", df.duplicated().sum())
