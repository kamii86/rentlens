import json
from pathlib import Path
from time import perf_counter

import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import pandas as pd
from mlflow.models import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import (
    mean_absolute_error,
    r2_score,
    root_mean_squared_error,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

plt.switch_backend("Agg")

SPLITS_DIR = Path("data/processed/splits")

# 1. Читаем настройки подготовленных выборок.
metadata_path = SPLITS_DIR / "metadata.json"
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

numeric_features = metadata["numeric_features"]
categorical_features = metadata["categorical_features"]
features = numeric_features + categorical_features
target = metadata["target"]

# Явно задаём типы для совместимости pandas, sklearn и MLflow.
column_types = {
    **dict.fromkeys(numeric_features, "float64"),
    **dict.fromkeys(categorical_features, "object"),
    "id": "object",
    target: "float64",
}

train_path = SPLITS_DIR / "train.csv"
validation_path = SPLITS_DIR / "validation.csv"

train = pd.read_csv(train_path, dtype=column_types)
validation = pd.read_csv(validation_path, dtype=column_types)

# X — входные характеристики, y — цена, которую предсказываем.
# ID и price не входят в X.
X_train = train[features]
y_train = train[target]

X_validation = validation[features]
y_validation = validation[target]

# 2. Обработка числовых признаков.
numeric_pipeline = Pipeline(
    steps=[
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ]
)

# 3. Обработка категорий.
categorical_pipeline = Pipeline(
    steps=[
        (
            "imputer",
            SimpleImputer(
                missing_values=pd.NA,
                strategy="constant",
                fill_value="unknown",
            ),
        ),
        (
            "encoder",
            OneHotEncoder(
                handle_unknown="ignore",
                sparse_output=True,
            ),
        ),
    ]
)

# 4. Объединяем обработку числовых и категориальных признаков.
preprocessor = ColumnTransformer(
    transformers=[
        ("numeric", numeric_pipeline, numeric_features),
        ("categorical", categorical_pipeline, categorical_features),
    ]
)

# 5. Создаём полную цепочку: обработка данных → модель.
regressor = LinearRegression()

model = Pipeline(
    steps=[
        ("preprocessor", preprocessor),
        ("regressor", regressor),
    ]
)

# 6. Подключаемся к MLflow.
mlflow.set_tracking_uri("http://127.0.0.1:5000")
mlflow.set_experiment("rentlens-training")

with mlflow.start_run(run_name="linear-regression-baseline") as run:
    mlflow.set_tags(
        {
            "model_family": "linear",
            "role": "baseline",
            "country": "USA",
        }
    )

    mlflow.log_params(
        {
            "model": "LinearRegression",
            "random_state": metadata["random_state"],
            "train_rows": len(train),
            "validation_rows": len(validation),
            "input_features": len(features),
            "numeric_imputation": "median",
            "categorical_imputation": "unknown",
            "source_sha256": metadata["source_sha256"],
        }
    )
    mlflow.log_params(regressor.get_params())

    # Связываем запуск с конкретными обучающими и проверочными данными.
    for frame, path, context in [
        (train, train_path, "training"),
        (validation, validation_path, "validation"),
    ]:
        dataset = mlflow.data.from_pandas(
            frame,
            source=str(path),
            name=f"us_apartments_{context}",
            targets=target,
        )
        mlflow.log_input(dataset, context=context)

    mlflow.log_artifact(str(metadata_path), artifact_path="data")

    # fit обучает и обработку признаков, и регрессию только на Train.
    print("Обучаем LinearRegression...")
    started = perf_counter()
    model.fit(X_train, y_train)
    training_seconds = perf_counter() - started

    # Для Validation применяем уже обученную обработку.
    predictions = model.predict(X_validation)

    metrics = {
        "validation_mae": float(mean_absolute_error(y_validation, predictions)),
        "validation_rmse": float(root_mean_squared_error(y_validation, predictions)),
        "validation_r2": float(r2_score(y_validation, predictions)),
        "training_seconds": training_seconds,
    }
    mlflow.log_metrics(metrics)

    # 7. Сохраняем предсказания для разбора ошибок.
    results = pd.DataFrame(
        {
            "id": validation["id"],
            "actual_price": y_validation,
            "predicted_price": predictions,
        }
    )
    results["absolute_error"] = (
        results["actual_price"] - results["predicted_price"]
    ).abs()

    mlflow.log_text(
        results.to_csv(index=False),
        "evaluation/validation_predictions.csv",
    )

    # График: реальные цены и предсказания на случайных 5000 примерах.
    sample = results.sample(
        n=min(5000, len(results)),
        random_state=metadata["random_state"],
    )

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(
        sample["actual_price"],
        sample["predicted_price"],
        alpha=0.3,
        s=10,
    )
    low = sample[["actual_price", "predicted_price"]].min().min()
    high = sample[["actual_price", "predicted_price"]].max().max()
    ax.plot([low, high], [low, high], "r--")
    ax.set_xlabel("Actual rent, USD/month")
    ax.set_ylabel("Predicted rent, USD/month")
    ax.set_title("LinearRegression — validation sample")
    fig.tight_layout()

    mlflow.log_figure(fig, "evaluation/actual_vs_predicted.png")
    plt.close(fig)

    # 8. Сохраняем всю модель вместе с обработкой признаков.
    signature = infer_signature(X_train, model.predict(X_train))

    model_info = mlflow.sklearn.log_model(
        sk_model=model,
        name="model",
        serialization_format="cloudpickle",
        signature=signature,
        input_example=X_train.dropna().head(3),
    )

    print("\nОБУЧЕНИЕ ЗАВЕРШЕНО")
    print(f"Validation MAE: ${metrics['validation_mae']:.2f}")
    print(f"Validation RMSE: ${metrics['validation_rmse']:.2f}")
    print(f"Validation R²: {metrics['validation_r2']:.4f}")
    print(f"Время обучения: {training_seconds:.2f} сек.")
    print("Run ID:", run.info.run_id)
    print("Model URI:", model_info.model_uri)
