import json
import runpy
from pathlib import Path

import pytest


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
