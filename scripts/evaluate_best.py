import hashlib
import json
from pathlib import Path
from time import perf_counter

import mlflow
import mlflow.pyfunc
import pandas as pd
from sklearn.metrics import (
    mean_absolute_error,
    r2_score,
    root_mean_squared_error,
)

mlflow.set_tracking_uri("http://127.0.0.1:5000")
mlflow.set_experiment("rentlens-training")

folder = Path("data/processed/splits")
reports = Path("reports")
reports.mkdir(exist_ok=True)

metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
selection = json.loads((reports / "selected_models.json").read_text(encoding="utf-8"))

if selection["primary_model"] != "RandomForestRegressor":
    raise ValueError("Ожидалась основная модель RandomForestRegressor.")

selected = next(
    item for item in selection["models"] if item["name"] == selection["primary_model"]
)

numeric = metadata["numeric_features"]
categorical = metadata["categorical_features"]
features = numeric + categorical
target = metadata["target"]

test_path = folder / "test.csv"

test = pd.read_csv(
    test_path,
    dtype={
        **dict.fromkeys(numeric, "float64"),
        **dict.fromkeys(categorical, "object"),
        "id": "object",
        target: "float64",
    },
)

if len(test) != metadata["rows"]["test"]:
    raise ValueError("Размер test.csv не совпадает с metadata.json.")

if test["id"].isna().any() or test["id"].duplicated().any():
    raise ValueError("В test.csv найдены пропуски или повторения ID.")

# Проверяем, что тестовые объявления не попали в другие выборки.
test_ids = set(test["id"])

for split_name in ["train", "validation"]:
    other = pd.read_csv(
        folder / f"{split_name}.csv",
        usecols=["id"],
        dtype={"id": "object"},
    )

    if test_ids.intersection(other["id"]):
        raise ValueError(f"Test пересекается с {split_name} по ID.")

with test_path.open("rb") as stream:
    test_sha256 = hashlib.file_digest(stream, "sha256").hexdigest()

print("Загружаем сохранённый RandomForest из MLflow...")
model = mlflow.pyfunc.load_model(selected["model_uri"])

print(f"Проверяем модель на {len(test)} тестовых объявлениях...")

started = perf_counter()
predictions = model.predict(test[features])
prediction_seconds = perf_counter() - started

metrics = {
    "test_mae": float(mean_absolute_error(test[target], predictions)),
    "test_rmse": float(root_mean_squared_error(test[target], predictions)),
    "test_r2": float(r2_score(test[target], predictions)),
    "test_prediction_seconds": prediction_seconds,
}

prediction_path = reports / "test_predictions.csv"
pd.DataFrame(
    {
        "id": test["id"],
        "actual_price": test[target],
        "predicted_price": predictions,
        "error": predictions - test[target],
        "absolute_error": abs(predictions - test[target]),
    }
).to_csv(prediction_path, index=False)

dataset = mlflow.data.from_pandas(
    test,
    source=str(test_path),
    name="us_apartments_test",
    targets=target,
)

with mlflow.start_run(
    run_name="random-forest-final-test",
    tags={
        "role": "final_evaluation",
        "model": "RandomForestRegressor",
    },
) as run:
    mlflow.log_params(
        {
            "evaluated_model_uri": selected["model_uri"],
            "training_run_id": selected["run_id"],
            "test_rows": len(test),
            "source_sha256": metadata["source_sha256"],
            "test_sha256": test_sha256,
        }
    )
    mlflow.log_input(dataset, context="testing")
    mlflow.log_metrics(metrics)

    summary = {
        "model": selected["name"],
        "model_uri": selected["model_uri"],
        "training_run_id": selected["run_id"],
        "evaluation_run_id": run.info.run_id,
        "validation_mae": selected["validation_mae"],
        "test_rows": len(test),
        "source_sha256": metadata["source_sha256"],
        "test_sha256": test_sha256,
        "metrics": metrics,
    }

    summary_path = reports / "final_evaluation.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    mlflow.log_artifact(str(prediction_path), artifact_path="evaluation")
    mlflow.log_artifact(str(summary_path), artifact_path="evaluation")
    mlflow.log_artifact(str(folder / "metadata.json"), artifact_path="data")

print("\nПРОВЕРКА НА TEST ЗАВЕРШЕНА")
print(f"Validation MAE: ${selected['validation_mae']:.2f}")
print(f"Test MAE: ${metrics['test_mae']:.2f}")
print(f"Test RMSE: ${metrics['test_rmse']:.2f}")
print(f"Test R²: {metrics['test_r2']:.4f}")
print("Run ID:", run.info.run_id)
print("Отчёт:", summary_path)
