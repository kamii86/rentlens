import json
from pathlib import Path

import mlflow
from mlflow.tracking import MlflowClient

mlflow.set_tracking_uri("http://127.0.0.1:5000")
client = MlflowClient()

MODEL_NAME = "rentlens-price"

selection = json.loads(Path("reports/selected_models.json").read_text(encoding="utf-8"))

if selection["primary_model"] != "RandomForestRegressor":
    raise ValueError("Основной моделью должен быть RandomForestRegressor.")

aliases = {
    "RandomForestRegressor": "champion",
    "CatBoostRegressor": "challenger",
}

for selected in selection["models"]:
    algorithm = selected["name"]

    if algorithm not in aliases:
        continue

    # При повторном запуске используем уже зарегистрированную версию.
    versions = client.search_model_versions(filter_string=f"name = '{MODEL_NAME}'")
    existing = [version for version in versions if version.run_id == selected["run_id"]]

    if existing:
        version = max(existing, key=lambda item: int(item.version))
    else:
        version = mlflow.register_model(
            model_uri=selected["model_uri"],
            name=MODEL_NAME,
        )

    client.set_model_version_tag(
        MODEL_NAME,
        version.version,
        "algorithm",
        algorithm,
    )
    client.set_registered_model_alias(
        MODEL_NAME,
        aliases[algorithm],
        version.version,
    )

    print(f"{algorithm}: версия {version.version}, метка {aliases[algorithm]}")

champion = client.get_model_version_by_alias(MODEL_NAME, "champion")

print("\nРЕГИСТРАЦИЯ ЗАВЕРШЕНА")
print("Основная модель:", champion.tags["algorithm"])
print("Версия:", champion.version)
print("URI для приложения:", f"models:/{MODEL_NAME}@champion")
