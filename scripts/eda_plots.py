from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

# 1. Загружаем очищенный датасет
df = pd.read_csv(
    "data/processed/apartments_clean.csv",
    low_memory=False,
)

# Папка для графиков
OUTPUT_DIR = Path("reports/figures")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 99-е процентили — для удобного отображения графиков
price_limit = df["price"].quantile(0.99)
area_limit = df["square_feet"].quantile(0.99)


# 2. Распределение стоимости аренды
plt.figure(figsize=(10, 6))

df.loc[df["price"] <= price_limit, "price"].hist(bins=50)

plt.title("Распределение стоимости аренды")
plt.xlabel("Аренда, USD/месяц")
plt.ylabel("Количество объявлений")

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "price_distribution.png", dpi=150)
plt.close()


# 3. Распределение площади квартир
plt.figure(figsize=(10, 6))

df.loc[df["square_feet"] <= area_limit, "square_feet"].hist(bins=50)

plt.title("Распределение площади квартир")
plt.xlabel("Площадь, ft²")
plt.ylabel("Количество объявлений")

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "area_distribution.png", dpi=150)
plt.close()


# 4. Зависимость стоимости аренды от площади
filtered = df[(df["price"] <= price_limit) & (df["square_feet"] <= area_limit)]

sample = filtered.sample(
    n=min(5000, len(filtered)),
    random_state=42,
)

plt.figure(figsize=(10, 6))

plt.scatter(
    sample["square_feet"],
    sample["price"],
    alpha=0.3,
    s=10,
)

plt.title("Зависимость аренды от площади")
plt.xlabel("Площадь, ft²")
plt.ylabel("Аренда, USD/месяц")

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "price_vs_area.png", dpi=150)
plt.close()


# 5. Медианная стоимость аренды по числу спален
bedrooms_data = df[df["bedrooms"].between(0, 5)]

median_prices = bedrooms_data.groupby("bedrooms")["price"].median()

plt.figure(figsize=(10, 6))

median_prices.plot(kind="bar")

plt.title("Медианная аренда по количеству спален")
plt.xlabel("Количество спален")
plt.ylabel("Медианная аренда, USD/месяц")
plt.xticks(rotation=0)

plt.tight_layout()
plt.savefig(OUTPUT_DIR / "price_by_bedrooms.png", dpi=150)
plt.close()


print("ГРАФИКИ УСПЕШНО СОХРАНЕНЫ")

for path in sorted(OUTPUT_DIR.glob("*.png")):
    print(path)
