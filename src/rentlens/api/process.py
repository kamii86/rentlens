import logging
import math
import os
from dataclasses import dataclass

import mlflow
import mlflow.pyfunc
import pandas as pd
from fastapi import APIRouter, HTTPException, Request
from mlflow.tracking import MlflowClient
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

logger = logging.getLogger(__name__)
router = APIRouter(tags=["prediction"])

NUMERIC_FEATURES = [
    "square_feet",
    "bedrooms",
    "bathrooms",
    "latitude",
    "longitude",
]

CATEGORICAL_FEATURES = [
    "cityname",
    "state",
    "pets_allowed",
]


class ApartmentInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )

    square_feet: float = Field(
        gt=0,
        description="Площадь квартиры в квадратных футах.",
    )
    bedrooms: int | None = Field(default=None, ge=0)
    bathrooms: float | None = Field(default=None, gt=0)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    cityname: str | None = Field(default=None, min_length=1)
    state: str | None = Field(default=None, min_length=1)
    pets_allowed: str | None = Field(default=None, min_length=1)


class PricePrediction(BaseModel):
    predicted_price: float
    currency: str
    price_type: str
    model_name: str
    model_version: str
    model_algorithm: str


@dataclass
class LoadedPriceModel:
    model: mlflow.pyfunc.PyFuncModel
    name: str
    version: str
    algorithm: str

    def predict(self, apartment: ApartmentInput) -> float:
        features = NUMERIC_FEATURES + CATEGORICAL_FEATURES
        frame = pd.DataFrame(
            [apartment.model_dump()],
            columns=features,
        )

        for column in NUMERIC_FEATURES:
            frame[column] = frame[column].astype("float64")

        for column in CATEGORICAL_FEATURES:
            frame[column] = frame[column].fillna("unknown").astype("object")

        price = float(self.model.predict(frame)[0])

        if not math.isfinite(price) or price <= 0:
            raise ValueError("Модель вернула некорректную цену.")

        return price


def load_price_model() -> LoadedPriceModel:
    tracking_uri = os.getenv(
        "MLFLOW_TRACKING_URI",
        "http://127.0.0.1:5000",
    )
    model_name = os.getenv("MLFLOW_MODEL_NAME", "rentlens-price")
    model_alias = os.getenv("MLFLOW_MODEL_ALIAS", "champion")

    mlflow.set_tracking_uri(tracking_uri)
    client = MlflowClient()

    version = client.get_model_version_by_alias(
        model_name,
        model_alias,
    )

    # Загружаем конкретную версию, выбранную при запуске.
    model_uri = f"models:/{model_name}/{version.version}"
    logger.info("Загрузка модели %s", model_uri)

    model = mlflow.pyfunc.load_model(model_uri)

    logger.info("Модель загружена: %s", model_uri)

    return LoadedPriceModel(
        model=model,
        name=model_name,
        version=str(version.version),
        algorithm=version.tags.get("algorithm", "unknown"),
    )


@router.post("/process", response_model=PricePrediction)
async def process(
    apartment: ApartmentInput,
    request: Request,
) -> PricePrediction:
    loaded = getattr(request.app.state, "price_model", None)

    if loaded is None:
        raise HTTPException(
            status_code=503,
            detail="Модель ещё не загружена.",
        )

    try:
        price = await run_in_threadpool(loaded.predict, apartment)
    except Exception as error:
        logger.exception("Ошибка предсказания цены")
        raise HTTPException(
            status_code=500,
            detail="Не удалось получить предсказание.",
        ) from error

    return PricePrediction(
        predicted_price=round(price, 2),
        currency="USD",
        price_type="monthly",
        model_name=loaded.name,
        model_version=loaded.version,
        model_algorithm=loaded.algorithm,
    )
