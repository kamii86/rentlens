import json
from pathlib import Path
from time import perf_counter

import catboost
import matplotlib.pyplot as plt
import mlflow
import mlflow.sklearn
import pandas as pd
from catboost import CatBoostRegressor
from mlflow.models import infer_signature
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    mean_absolute_error,
    r2_score,
    root_mean_squared_error,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

plt.switch_backend("Agg")

SPLITS_DIR = Path("data/processed/splits")

# 1. Загружаем настройки и подготовленные выборки.
metadata_path = SPLITS_DIR / "metadata.json"
metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

numeric_features = metadata["numeric_features"]
categorical_features = metadata["categorical_features"]
features = numeric_features + categorical_features
target = metadata["target"]

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

X_train = train[features]
y_train = train[target]
X_validation = validation[features]
y_validation = validation[target]

# 2. Создаём обработку признаков.
numeric_pipeline = Pipeline(
    steps=[
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ]
)

categorical_imputer = SimpleImputer(
    missing_values=pd.NA,
    strategy="constant",
    fill_value="unknown",
)

preprocessor = ColumnTransformer(
    transformers=[
        ("numeric", numeric_pipeline, numeric_features),
        ("categorical", categorical_imputer, categorical_features),
    ]
)

categorical_indices = list(range(len(numeric_features), len(features)))

# 3. Создаём один выбранный вариант CatBoost.
regressor = CatBoostRegressor(
    iterations=2000,
    depth=8,
    learning_rate=0.05,
    loss_function="MAE",
    eval_metric="MAE",
    cat_features=categorical_indices,
    random_seed=metadata["random_state"],
    thread_count=-1,
    verbose=False,
    allow_writing_files=False,
)

mlflow.set_tracking_uri("http://127.0.0.1:5000")
mlflow.set_experiment("rentlens-training")

with mlflow.start_run(run_name="catboost") as run:
    mlflow.set_tags(
        {
            "model_family": "gradient_boosting",
            "role": "candidate",
            "country": "USA",
        }
    )

    mlflow.log_params(
        {
            "model": "CatBoostRegressor",
            "random_state": metadata["random_state"],
            "train_rows": len(train),
            "validation_rows": len(validation),
            "input_features": len(features),
            "numeric_imputation": "median",
            "categorical_imputation": "unknown",
            "categorical_encoding": "native",
            "early_stopping_rounds": 100,
            "use_best_model": True,
            "source_sha256": metadata["source_sha256"],
        }
    )
    mlflow.log_params(regressor.get_params())

    # 4. Привязываем датасеты к запуску.
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

    # 5. Обучаем обработку только на Train.
    print("Обучаем CatBoostRegressor...", flush=True)
    started = perf_counter()

    prepared_train = preprocessor.fit_transform(X_train)
    prepared_validation = preprocessor.transform(X_validation)

    # Validation используется для выбора лучшей итерации.
    regressor.fit(
        prepared_train,
        y_train,
        eval_set=(prepared_validation, y_validation),
        early_stopping_rounds=100,
        use_best_model=True,
    )
    training_seconds = perf_counter() - started

    # Объединяем уже обученные части в одну сохраняемую модель.
    model = Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("regressor", regressor),
        ]
    )

    # 6. Считаем метрики.
    train_predictions = model.predict(X_train)
    predictions = model.predict(X_validation)

    metrics = {
        "train_mae": float(mean_absolute_error(y_train, train_predictions)),
        "validation_mae": float(mean_absolute_error(y_validation, predictions)),
        "validation_rmse": float(root_mean_squared_error(y_validation, predictions)),
        "validation_r2": float(r2_score(y_validation, predictions)),
        "training_seconds": training_seconds,
        "actual_trees": int(regressor.tree_count_),
    }
    mlflow.log_metrics(metrics)
    mlflow.log_param(
        "best_iteration",
        int(regressor.get_best_iteration()),
    )

    # 7. Сохраняем предсказания и ошибки.
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

    # 8. Сохраняем историю и график обучения.
    curves = regressor.get_evals_result()
    mlflow.log_dict(curves, "evaluation/learning_curves.json")

    fig, ax = plt.subplots(figsize=(9, 6))

    for dataset_name, history in curves.items():
        if "MAE" in history:
            ax.plot(history["MAE"], label=dataset_name)

    ax.axvline(
        regressor.get_best_iteration(),
        color="black",
        linestyle="--",
        label="Best iteration",
    )
    ax.set_xlabel("Iteration")
    ax.set_ylabel("MAE, USD/month")
    ax.set_title("CatBoost — depth 8, MAE")
    ax.legend()
    fig.tight_layout()

    mlflow.log_figure(fig, "evaluation/learning_curve.png")
    plt.close(fig)

    # 9. Сохраняем модель вместе с обработкой признаков.
    signature = infer_signature(X_train, train_predictions)

    model_info = mlflow.sklearn.log_model(
        sk_model=model,
        name="model",
        serialization_format="cloudpickle",
        signature=signature,
        input_example=X_train.dropna().head(3),
        extra_pip_requirements=[
            f"catboost=={catboost.__version__}",
        ],
    )

    print("\nОБУЧЕНИЕ ЗАВЕРШЕНО")
    print(f"Train MAE: ${metrics['train_mae']:.2f}")
    print(f"Validation MAE: ${metrics['validation_mae']:.2f}")
    print(f"Validation RMSE: ${metrics['validation_rmse']:.2f}")
    print(f"Validation R²: {metrics['validation_r2']:.4f}")
    print("Сохранено деревьев:", regressor.tree_count_)
    print("Run ID:", run.info.run_id)
    print("Model URI:", model_info.model_uri)
