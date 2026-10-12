from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

import rentlens.main as main_module
from rentlens.api.process import LoadedPriceModel


@pytest.fixture
def model_loader(monkeypatch: pytest.MonkeyPatch) -> Mock:
    fake_model = Mock()
    fake_model.predict.return_value = [1500.50]

    loaded = LoadedPriceModel(
        model=fake_model,
        name="rentlens-price",
        version="1",
        algorithm="RandomForestRegressor",
    )

    loader = Mock(return_value=loaded)
    monkeypatch.setattr(main_module, "load_price_model", loader)

    return loader


@pytest.mark.asyncio
async def test_process_success_and_single_loading(model_loader: Mock) -> None:
    app = main_module.app

    async with main_module.lifespan(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            payload = {
                "square_feet": 900,
                "bedrooms": 2,
                "bathrooms": 1,
                "latitude": 40.7128,
                "longitude": -74.0060,
                "cityname": "New York",
                "state": "NY",
                "pets_allowed": "Cats,Dogs",
            }

            for _ in range(2):
                response = await client.post("/process", json=payload)

                assert response.status_code == 200
                assert response.json() == {
                    "predicted_price": 1500.50,
                    "currency": "USD",
                    "price_type": "monthly",
                    "model_name": "rentlens-price",
                    "model_version": "1",
                    "model_algorithm": "RandomForestRegressor",
                }

        model_loader.assert_called_once_with()
        assert model_loader.return_value.model.predict.call_count == 2

    assert app.state.price_model is None


@pytest.mark.asyncio
async def test_process_missing_optional_features(model_loader: Mock) -> None:
    app = main_module.app

    async with main_module.lifespan(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/process",
                json={"square_feet": 900},
            )

        assert response.status_code == 200

        frame = model_loader.return_value.model.predict.call_args.args[0]

        assert frame["bedrooms"].isna().all()
        assert frame["bathrooms"].isna().all()
        assert frame["cityname"].iloc[0] == "unknown"
        assert frame["state"].iloc[0] == "unknown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"square_feet": -100},
        {"square_feet": 900, "bedrooms": -1},
        {"square_feet": 900, "latitude": 100},
        {"square_feet": 900, "unexpected_field": "value"},
        {},
    ],
)
async def test_process_invalid_input(
    model_loader: Mock,
    payload: dict,
) -> None:
    app = main_module.app

    async with main_module.lifespan(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post("/process", json=payload)

        assert response.status_code == 422
        model_loader.return_value.model.predict.assert_not_called()


@pytest.mark.asyncio
async def test_process_prediction_failure(model_loader: Mock) -> None:
    model_loader.return_value.model.predict.side_effect = RuntimeError(
        "Prediction failed"
    )
    app = main_module.app

    async with main_module.lifespan(app):
        transport = ASGITransport(app=app)

        async with AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/process",
                json={"square_feet": 900},
            )

        assert response.status_code == 500
        assert response.json() == {"detail": "Не удалось получить предсказание."}


@pytest.mark.asyncio
async def test_process_model_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = main_module.app
    monkeypatch.setattr(app.state, "price_model", None, raising=False)

    transport = ASGITransport(app=app)

    async with AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/process",
            json={"square_feet": 900},
        )

    assert response.status_code == 503
    assert response.json() == {"detail": "Модель ещё не загружена."}
