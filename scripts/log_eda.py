from pathlib import Path

import mlflow
import pandas as pd

# 1. Подключаемся к серверу MLflow
mlflow.set_tracking_uri("http://127.0.0.1:5000")

# 2. Создаём эксперимент
mlflow.set_experiment("rentlens-eda")

# 3. Указываем пути к данным и графикам
DATA_PATH = Path("data/processed/apartments_clean.csv")
FIGURES_DIR = Path("reports/figures")

# 4. Загружаем очищенный датасет
df = pd.read_csv(DATA_PATH, low_memory=False)

# Регистрируем датасет как объект MLflow
dataset = mlflow.data.from_pandas(
    df,
    source=str(DATA_PATH),
    name="us_apartments_clean",
    targets="price",
)

# 5. Начинаем Run
with mlflow.start_run(run_name="eda-us-apartments-after-cleaning"):
    # Связываем датасет с текущим запуском
    mlflow.log_input(dataset, context="analysis")

    # Сохраняем причины исключения объявлений.
    exclusions_path = Path("reports/excluded_records.csv")
    exclusions = pd.read_csv(exclusions_path)

    mlflow.log_param("manually_excluded_records", len(exclusions))
    mlflow.log_artifact(str(exclusions_path), artifact_path="eda")

    # Сохраняем параметры
    mlflow.log_param("dataset", DATA_PATH.name)
    mlflow.log_param("country", "USA")
    mlflow.log_param("rental_period", "Monthly")

    # Сохраняем статистические показатели
    mlflow.log_metric("total_apartments", len(df))
    mlflow.log_metric("total_features", len(df.columns))
    mlflow.log_metric("median_price", float(df["price"].median()))
    mlflow.log_metric("mean_price", float(df["price"].mean()))
    mlflow.log_metric("median_area", float(df["square_feet"].median()))

    # Сохраняем графики как артефакты
    mlflow.log_artifacts(
        str(FIGURES_DIR),
        artifact_path="eda/figures",
    )

    # Формируем краткий текстовый отчёт
    report = f"""
EDA — US Apartments Rental Dataset

Количество квартир: {len(df)}
Количество признаков: {len(df.columns)}

Медианная аренда: ${df["price"].median():.2f}
Средняя аренда: ${df["price"].mean():.2f}
Медианная площадь: {df["square_feet"].median():.2f} ft²

Основные выводы:
1. Распределение стоимости аренды смещено вправо.
2. Большинство квартир имеют площадь примерно 600–1200 ft².
3. Стоимость аренды в целом растёт с увеличением площади.
4. Количество спален связано со стоимостью аренды.
5. В данных присутствуют потенциальные выбросы.
"""

    # Сохраняем отчёт в MLflow
    mlflow.log_text(report, "eda/summary.txt")

    print("EDA успешно сохранён в MLflow!")
    print("Количество квартир:", len(df))
    print("Количество графиков:", len(list(FIGURES_DIR.glob("*.png"))))
