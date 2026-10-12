from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import rentlens.api.process as process_module
from rentlens.api.process import ApartmentInput, LoadedPriceModel


def test_load_model_pins_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://mlflow:5000")
    monkeypatch.setenv("MLFLOW_MODEL_NAME", "rentlens-price")
    monkeypatch.setenv("MLFLOW_MODEL_ALIAS", "champion")

    version = SimpleNamespace(
        version="2",
        tags={"algorithm": "CatBoostRegressor"},
    )
    client = Mock()
    client.get_model_version_by_alias.return_value = version

    client_factory = Mock(return_value=client)
    set_tracking_uri = Mock()
    fake_model = Mock()
    load_model = Mock(return_value=fake_model)

    monkeypatch.setattr(process_module, "MlflowClient", client_factory)
    monkeypatch.setattr(
        process_module.mlflow,
        "set_tracking_uri",
        set_tracking_uri,
    )
    monkeypatch.setattr(
        process_module.mlflow.pyfunc,
        "load_model",
        load_model,
    )

    loaded = process_module.load_price_model()

    set_tracking_uri.assert_called_once_with("http://mlflow:5000")
    client.get_model_version_by_alias.assert_called_once_with(
        "rentlens-price",
        "champion",
    )

    # После получения alias загружается конкретная версия.
    load_model.assert_called_once_with("models:/rentlens-price/2")

    assert loaded.model is fake_model
    assert loaded.name == "rentlens-price"
    assert loaded.version == "2"
    assert loaded.algorithm == "CatBoostRegressor"


@pytest.mark.parametrize(
    "price",
    [float("nan"), float("inf"), -100.0, 0.0],
)
def test_model_rejects_invalid_price(price: float) -> None:
    fake_model = Mock()
    fake_model.predict.return_value = [price]

    loaded = LoadedPriceModel(
        model=fake_model,
        name="rentlens-price",
        version="1",
        algorithm="RandomForestRegressor",
    )

    with pytest.raises(ValueError, match="некорректную цену"):
        loaded.predict(ApartmentInput(square_feet=900))
