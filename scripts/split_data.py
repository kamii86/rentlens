import hashlib
import json
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

DATA_PATH = Path("data/processed/apartments_clean.csv")
OUTPUT_DIR = Path("data/processed/splits")
RANDOM_STATE = 42

TARGET = "price"

NUMERIC_FEATURES = [
    "square_feet",
    "bedrooms",
    "bathrooms",
    "latitude",
    "longitude",
]

CATEGORICAL_FEATURES = [
    "cityname",
    "state",
    "pets_allowed",
]

# 1. Загружаем очищенные данные.
df = pd.read_csv(
    DATA_PATH,
    dtype={"id": "string"},
    low_memory=False,
)

# ID нужен для проверки и отслеживания записей, не для обучения.
if df["id"].isna().any() or df["id"].duplicated().any():
    raise ValueError("ID объявлений должны быть заполнены и уникальны.")

# 2. Оставляем ID, целевую переменную и выбранные признаки.
columns = ["id", TARGET] + NUMERIC_FEATURES + CATEGORICAL_FEATURES
df = df[columns].copy()

# 3. Отделяем 70% для обучения, остальные 30% пока оставляем вместе.
train, remaining = train_test_split(
    df,
    test_size=0.30,
    random_state=RANDOM_STATE,
)

# 4. Делим оставшиеся 30% пополам: validation и test.
validation, test = train_test_split(
    remaining,
    test_size=0.50,
    random_state=RANDOM_STATE,
)

# 5. Сохраняем выборки отдельными файлами.
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

splits = {
    "train": train,
    "validation": validation,
    "test": test,
}

for name, split in splits.items():
    path = OUTPUT_DIR / f"{name}.csv"
    split.to_csv(path, index=False, encoding="utf-8")
    print(f"{name}: {len(split)} объявлений → {path}")

# 6. Фиксируем источник данных и настройки разделения.
with DATA_PATH.open("rb") as file:
    source_sha256 = hashlib.file_digest(file, "sha256").hexdigest()

metadata = {
    "source": str(DATA_PATH),
    "source_sha256": source_sha256,
    "random_state": RANDOM_STATE,
    "target": TARGET,
    "numeric_features": NUMERIC_FEATURES,
    "categorical_features": CATEGORICAL_FEATURES,
    "fractions": {"train": 0.70, "validation": 0.15, "test": 0.15},
    "rows": {name: len(split) for name, split in splits.items()},
}

metadata_path = OUTPUT_DIR / "metadata.json"
metadata_path.write_text(
    json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

print("\nРАЗДЕЛЕНИЕ ЗАВЕРШЕНО")
print("Количество входных признаков:", len(columns) - 2)
print("Настройки сохранены:", metadata_path)
