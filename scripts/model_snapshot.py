"""Сохраняет champion вне Docker-томов и восстанавливает его в новом MLflow."""

import argparse
import hashlib
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import mlflow
import mlflow.sklearn
from mlflow.models import Model
from mlflow.tracking import MlflowClient


def file_hashes(directory: Path) -> dict[str, str]:
    result = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            with path.open("rb") as stream:
                result[path.relative_to(directory).as_posix()] = hashlib.file_digest(
                    stream, "sha256"
                ).hexdigest()
    return result


def verify_snapshot(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest.get("format_version") != 1:
        raise ValueError("Неизвестный формат снимка")
    model_dir = directory / "model"
    if not (model_dir / "MLmodel").is_file():
        raise ValueError("В снимке отсутствует MLmodel")
    if file_hashes(model_dir) != manifest["sha256"]:
        raise ValueError("Снимок повреждён: контрольные суммы не совпадают")
    return manifest


def export_snapshot(client: MlflowClient, directory: Path, name: str, alias: str):
    version = client.get_model_version_by_alias(name, alias)
    if directory.exists():
        manifest = verify_snapshot(directory)
        if (
            manifest["model_name"] == name
            and manifest["model_version"] == version.version
            and manifest["run_id"] == version.run_id
        ):
            print("Проверен существующий снимок:", directory)
            return
        raise FileExistsError("Выберите другую --directory для новой модели")

    directory.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=directory.parent) as temporary:
        temporary = Path(temporary)
        download = temporary / "download"
        download.mkdir()
        downloaded = mlflow.artifacts.download_artifacts(
            artifact_uri=f"models:/{name}/{version.version}",
            dst_path=str(download),
        )
        staging = temporary / "snapshot"
        staging.mkdir()
        shutil.move(downloaded, staging / "model")
        manifest = {
            "format_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "model_name": name,
            "model_version": version.version,
            "alias": alias,
            "run_id": version.run_id,
            "algorithm": version.tags.get("algorithm", "RandomForestRegressor"),
            "sha256": file_hashes(staging / "model"),
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        verify_snapshot(staging)
        staging.rename(directory)
    print("Снимок сохранён и проверен:", directory)


def restore_snapshot(client: MlflowClient, directory: Path, name: str, alias: str):
    manifest = verify_snapshot(directory)
    with (directory / "manifest.json").open("rb") as stream:
        snapshot_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    versions = client.search_model_versions(f"name='{name}'")
    existing = [
        version
        for version in versions
        if version.tags.get("snapshot.sha256") == snapshot_hash
    ]
    if existing:
        version = max(existing, key=lambda item: int(item.version))
    else:
        model_dir = directory / "model"
        metadata = Model.load(str(model_dir / "MLmodel"))
        model = mlflow.sklearn.load_model(str(model_dir))
        mlflow.set_experiment("rentlens-restored")
        with mlflow.start_run(run_name="restore-champion"):
            mlflow.set_tags(
                {
                    "snapshot.sha256": snapshot_hash,
                    "snapshot.original_run_id": manifest["run_id"],
                    "model_family": "random_forest",
                }
            )
            mlflow.log_artifact(str(directory / "manifest.json"), "snapshot")
            info = mlflow.sklearn.log_model(
                sk_model=model,
                name="model",
                signature=metadata.signature,
            )
            version = mlflow.register_model(info.model_uri, name)
        client.set_model_version_tag(
            name, version.version, "snapshot.sha256", snapshot_hash
        )
        client.set_model_version_tag(
            name, version.version, "algorithm", manifest["algorithm"]
        )
    client.set_registered_model_alias(name, alias, version.version)
    print(f"Восстановлено: models:/{name}@{alias}, версия {version.version}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["export", "verify", "restore"])
    parser.add_argument(
        "--directory", type=Path, default=Path("model-snapshots/champion")
    )
    parser.add_argument("--name", default="rentlens-price")
    parser.add_argument("--alias", default="champion")
    parser.add_argument(
        "--tracking-uri",
        default=os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"),
    )
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.action == "verify":
        verify_snapshot(directory)
        print("Контрольные суммы совпадают:", directory)
        return
    mlflow.set_tracking_uri(args.tracking_uri)
    client = MlflowClient()
    if args.action == "export":
        export_snapshot(client, directory, args.name, args.alias)
    else:
        restore_snapshot(client, directory, args.name, args.alias)


if __name__ == "__main__":
    main()
