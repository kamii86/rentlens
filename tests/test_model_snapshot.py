import json
import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from mlflow.exceptions import MlflowException
from mlflow.protos.databricks_pb2 import PERMISSION_DENIED, RESOURCE_DOES_NOT_EXIST


@pytest.fixture
def snapshot(tmp_path):
    functions = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts" / "model_snapshot.py")
    )
    model = tmp_path / "model"
    model.mkdir()
    (model / "MLmodel").write_text("model metadata")
    (model / "model.pkl").write_bytes(b"original model weights")
    manifest = {"format_version": 1, "sha256": functions["file_hashes"](model)}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return functions["verify_snapshot"], tmp_path


@pytest.mark.parametrize("change", ["overwrite", "add", "remove"])
def test_snapshot_rejects_changed_missing_or_extra_files(snapshot, change):
    verify, directory = snapshot
    verify(directory)
    if change == "overwrite":
        (directory / "model/model.pkl").write_bytes(b"different weights")
    elif change == "add":
        (directory / "model/extra.pkl").write_bytes(b"unexpected file")
    else:
        (directory / "model/model.pkl").unlink()
    with pytest.raises(ValueError, match="контрольные суммы"):
        verify(directory)


def test_snapshot_without_model_metadata_is_rejected(snapshot):
    verify, directory = snapshot
    (directory / "model/MLmodel").unlink()
    with pytest.raises(ValueError, match="отсутствует MLmodel"):
        verify(directory)


def test_ensure_keeps_existing_champion_without_snapshot(snapshot, monkeypatch):
    verify, directory = snapshot
    ensure = verify.__globals__["ensure_model"]
    restore = Mock()
    monkeypatch.setitem(ensure.__globals__, "restore_snapshot", restore)
    version = SimpleNamespace(version="7", status="READY")
    client = Mock()
    client.get_registered_model.return_value = SimpleNamespace(
        aliases={"champion": "7"}
    )
    client.get_model_version.return_value = version

    assert ensure(client, directory / "absent", "price", "champion") is version
    restore.assert_not_called()


@pytest.mark.parametrize("registered_exists", [True, False])
def test_ensure_restores_missing_champion(snapshot, monkeypatch, registered_exists):
    verify, directory = snapshot
    ensure = verify.__globals__["ensure_model"]
    restored = SimpleNamespace(version="1", status="READY")
    restore = Mock(return_value=restored)
    monkeypatch.setitem(ensure.__globals__, "restore_snapshot", restore)
    client = Mock()
    if registered_exists:
        client.get_registered_model.return_value = SimpleNamespace(aliases={})
    else:
        client.get_registered_model.side_effect = MlflowException(
            "not found", RESOURCE_DOES_NOT_EXIST
        )

    assert ensure(client, directory, "price", "champion") is restored
    restore.assert_called_once_with(client, directory, "price", "champion")


def test_ensure_does_not_hide_registry_errors(snapshot, monkeypatch):
    verify, directory = snapshot
    ensure = verify.__globals__["ensure_model"]
    restore = Mock()
    monkeypatch.setitem(ensure.__globals__, "restore_snapshot", restore)
    client = Mock()
    client.get_registered_model.side_effect = MlflowException(
        "denied", PERMISSION_DENIED
    )
    with pytest.raises(MlflowException, match="denied"):
        ensure(client, directory, "price", "champion")
    restore.assert_not_called()


def test_ensure_does_not_replace_unready_champion(snapshot, monkeypatch):
    verify, directory = snapshot
    ensure = verify.__globals__["ensure_model"]
    restore = Mock()
    monkeypatch.setitem(ensure.__globals__, "restore_snapshot", restore)
    client = Mock()
    client.get_registered_model.return_value = SimpleNamespace(
        aliases={"champion": "7"}
    )
    client.get_model_version.return_value = SimpleNamespace(
        status="FAILED_REGISTRATION"
    )
    with pytest.raises(RuntimeError, match="не готова"):
        ensure(client, directory, "price", "champion")
    restore.assert_not_called()


def test_ensure_requires_snapshot_when_registry_is_empty(snapshot):
    verify, directory = snapshot
    ensure = verify.__globals__["ensure_model"]
    client = Mock()
    client.get_registered_model.side_effect = MlflowException(
        "not found", RESOURCE_DOES_NOT_EXIST
    )
    with pytest.raises(FileNotFoundError, match="снимок отсутствует"):
        ensure(client, directory / "absent", "price", "champion")


def test_ensure_rejects_corrupt_snapshot_before_registry_write(snapshot):
    verify, directory = snapshot
    ensure = verify.__globals__["ensure_model"]
    client = Mock()
    client.get_registered_model.side_effect = MlflowException(
        "not found", RESOURCE_DOES_NOT_EXIST
    )
    (directory / "model/model.pkl").write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="контрольные суммы"):
        ensure(client, directory, "price", "champion")
    client.search_model_versions.assert_not_called()


def test_ensure_restores_prediction_and_is_idempotent(tmp_path, monkeypatch):
    import mlflow
    import mlflow.sklearn
    import pandas as pd
    from mlflow.models import infer_signature
    from mlflow.tracking import MlflowClient
    from sklearn.dummy import DummyRegressor

    functions = runpy.run_path(
        str(Path(__file__).resolve().parents[1] / "scripts" / "model_snapshot.py")
    )
    directory = tmp_path / "snapshot"
    directory.mkdir()
    frame = pd.DataFrame({"square_feet": [500.0, 700.0]})
    model = DummyRegressor(strategy="constant", constant=945.32).fit(frame, [1, 2])
    mlflow.sklearn.save_model(
        model,
        str(directory / "model"),
        signature=infer_signature(frame, model.predict(frame)),
        pip_requirements=[],
    )
    manifest = {
        "format_version": 1,
        "run_id": "original-run",
        "algorithm": "DummyRegressor",
        "sha256": functions["file_hashes"](directory / "model"),
    }
    (directory / "manifest.json").write_text(json.dumps(manifest))
    uri = (tmp_path / "mlruns").as_uri()
    previous_uri = mlflow.get_tracking_uri()
    monkeypatch.setenv("MLFLOW_REGISTRY_URI", uri)
    try:
        mlflow.set_tracking_uri(uri)
        client = MlflowClient(tracking_uri=uri)
        client.create_experiment(
            "rentlens-restored", artifact_location=(tmp_path / "artifacts").as_uri()
        )
        client.create_registered_model("audit-price")
        ensure = functions["ensure_model"]
        first = ensure(client, directory, "audit-price", "champion")
        repeated = ensure(client, directory, "audit-price", "champion")
        assert first.version == repeated.version
        assert len(client.search_model_versions("name='audit-price'")) == 1
        alias = client.get_model_version_by_alias("audit-price", "champion")
        restored = mlflow.sklearn.load_model(f"models:/audit-price/{alias.version}")
        assert restored.predict(frame).tolist() == pytest.approx([945.32, 945.32])
        assert alias.run_id
        assert alias.tags["algorithm"] == "DummyRegressor"

        project = Path(__file__).resolve().parents[1]
        process = subprocess.run(
            [
                sys.executable,
                str(project / "scripts/model_snapshot.py"),
                "restore",
                "--directory",
                str(directory),
                "--tracking-uri",
                uri,
                "--name",
                "cli-price",
            ],
            env={
                **os.environ,
                "PYTHONPATH": str(project / "src"),
                "MLFLOW_REGISTRY_URI": uri,
                "MLFLOW_SUPPRESS_PRINTING_URL_TO_STDOUT": "true",
            },
            cwd=tmp_path,
            text=True,
            capture_output=True,
            timeout=60,
            check=True,
        )
        assert not process.stderr
        records = [json.loads(line) for line in process.stdout.splitlines()]
        assert any(record.get("event") == "model_restored" for record in records)
    finally:
        mlflow.set_tracking_uri(previous_uri)
