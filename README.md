# RentLens

RentLens — учебный сервис прогнозирования месячной стоимости аренды квартир в США.

Пользователь передаёт параметры квартиры в API, а сервис возвращает оценку аренды в долларах и информацию об использованной модели.

Проект включает подготовку данных, EDA, обучение и сравнение моделей, отслеживание экспериментов в MLflow, Model Registry и асинхронный API на FastAPI.

## Возможности

- очистка датасета и отчёт об исключённых объявлениях;
- исследовательский анализ данных с графиками;
- разделение данных на train, validation и test;
- обучение LinearRegression, RandomForestRegressor и CatBoostRegressor;
- сохранение параметров, метрик, датасетов и артефактов в MLflow;
- регистрация моделей и выбор рабочей версии через alias `champion`;
- загрузка модели один раз при запуске приложения;
- асинхронный `POST /process`;
- проверка состояния приложения и PostgreSQL;
- автоматические тесты, Ruff и pre-commit;
- контейнеризация через Docker Compose;
- CI и публикация Docker-образов через GitHub Actions.

## Данные

Используется версия 100K открытого датасета
[Apartment for Rent Classified](https://archive.ics.uci.edu/dataset/555/apartment+for+rent+classified)
из UCI Machine Learning Repository.

Источник: https://doi.org/10.24432/C5X623
Лицензия: CC BY 4.0.

Датасет содержит исторические объявления об аренде в США. Прогнозы отражают зависимости в этих данных и не являются подтверждением актуальной рыночной цены.

Единицы измерения:

- `price` — месячная аренда в долларах США;
- `square_feet` — площадь в квадратных футах;
- `bedrooms` — количество спален; `0` означает студию;
- `bathrooms` — количество ванных комнат;
- `latitude`, `longitude` — географические координаты.

В процессе очистки удаляются полные дубликаты, объявления с другой валютой или периодом оплаты и записи с некорректной ценой или площадью.

После ручной проверки исключены ещё четыре объявления с ошибочными или неподтверждёнными значениями. Причины сохранены в `reports/excluded_records.csv`.

Итоговый датасет: **99 399 объявлений, 22 столбца**.

Для обучения используются восемь признаков:

- `square_feet`;
- `bedrooms`;
- `bathrooms`;
- `latitude`;
- `longitude`;
- `cityname`;
- `state`;
- `pets_allowed`.

Цена является целевой переменной. ID объявления сохраняется для проверки и трассировки, но не используется как входной признак.

## Разделение данных и preprocessing

Разделение воспроизводимо: `random_state=42`.

| Выборка | Доля | Объявлений | Назначение |
|---|---:|---:|---|
| Train | 70% | 69 579 | Обучение |
| Validation | 15% | 14 910 | Сравнение и настройка моделей |
| Test | 15% | 14 910 | Финальная проверка выбранной модели |

Параметры preprocessing вычисляются на train.

Числовые пропуски заполняются медианой, затем применяется StandardScaler.

Для LinearRegression и RandomForest категориальные признаки кодируются через OneHotEncoder с обработкой неизвестных категорий.

CatBoost получает категориальные признаки без OneHotEncoder. Пропуски в категориях заменяются на `unknown`.

Preprocessing и регрессор сохраняются вместе в одном Pipeline.

## Результаты моделей

Основная метрика — MAE: средняя абсолютная ошибка в долларах за месяц. Дополнительные метрики — RMSE и R².

Результаты выбранных конфигураций на validation:

| Модель | MAE, USD | RMSE, USD | R² |
|---|---:|---:|---:|
| LinearRegression | 275,73 | 529,25 | 0,6318 |
| RandomForestRegressor | **204,06** | **404,56** | **0,7849** |
| CatBoostRegressor | 208,60 | 444,54 | 0,7403 |

LinearRegression используется как базовая модель.

Основной выбран RandomForest: среди оставленных конфигураций он показал наименьшие MAE и RMSE на validation.

Параметры RandomForest:

- `n_estimators=200`;
- `max_depth=20`;
- `min_samples_leaf=2`;
- `max_features=0.5`;
- `random_state=42`.

Выбранный CatBoost:

- `iterations=2000`;
- `depth=8`;
- `learning_rate=0.05`;
- `loss_function="MAE"`;
- `eval_metric="MAE"`;
- `early_stopping_rounds=100`;
- `random_seed=42`.

Финальная проверка RandomForest на test:

| Метрика | Значение |
|---|---:|
| MAE | $204,73 |
| RMSE | $416,57 |
| R² | 0,7765 |

Результаты сохранены в `reports/final_evaluation.json`.
Предсказания по тестовым объявлениям — в `reports/test_predictions.csv`.

## Технологии

Python 3.12, FastAPI, Uvicorn, PostgreSQL 17, SQLAlchemy, asyncpg,
pandas, matplotlib, scikit-learn, CatBoost, MLflow 3.5.1,
uv, pytest, httpx, Ruff, pre-commit, Docker, GitHub Actions и GHCR.

## Основные файлы

| Файл или папка | Назначение |
|---|---|
| `src/rentlens/main.py` | Создание приложения и загрузка модели при запуске |
| `src/rentlens/api/process.py` | Валидация параметров и предсказание цены |
| `src/rentlens/api/health.py` | Проверки состояния и версия приложения |
| `src/rentlens/config.py` | Настройки приложения |
| `src/rentlens/database.py` | Подключение к PostgreSQL |
| `src/rentlens/logging_config.py` | Настройка логирования |
| `scripts/clean_data.py` | Очистка исходного датасета |
| `scripts/eda_overview.py` | Обзор данных |
| `scripts/eda_plots.py` | Построение графиков |
| `scripts/log_eda.py` | Сохранение EDA в MLflow |
| `scripts/split_data.py` | Создание train, validation и test |
| `scripts/train_linear.py` | Обучение LinearRegression |
| `scripts/train_forest.py` | Обучение RandomForest |
| `scripts/train_catboost.py` | Обучение выбранной конфигурации CatBoost |
| `scripts/evaluate_best.py` | Проверка основной модели на test |
| `scripts/register_models.py` | Регистрация моделей и назначение aliases |
| `reports/selected_models.json` | Выбранные модели и ссылки на их запуски |
| `tests/` | Проверки API и загрузки модели |
| `Dockerfile` | Образ приложения |
| `Dockerfile.mlflow` | Образ MLflow |
| `compose.yaml` | Приложение, MLflow и две базы PostgreSQL |
| `pyproject.toml`, `uv.lock` | Зависимости и настройки инструментов |

## Установка

Необходимы Python 3.12, uv и Docker с Docker Compose.

```bash
git clone git@github.com:kamii86/rentlens.git
cd rentlens
uv sync --all-groups
```

Группа `web` содержит зависимости веб-приложения.
Группа `dev` — инструменты разработки и тестирования.
MLflow, библиотеки обработки данных и модели входят в основные зависимости.

Создайте файл настроек:

```bash
cp .env.example .env
```

Укажите в `.env` свой `MLFLOW_DB_PASSWORD`.
Файл `.env` не добавляется в Git.

## Docker Compose

Используются четыре сервиса:

| Сервис | Назначение |
|---|---|
| `app` | FastAPI, порт 8000 |
| `db` | PostgreSQL приложения |
| `mlflow` | Tracking Server и Model Registry, порт 5000 |
| `mlflow-db` | PostgreSQL для метаданных MLflow |

Backend Store MLflow размещён в отдельной PostgreSQL.
Artifact Store размещён в volume `mlflow_artifacts`.
Артефакты передаются клиентам через MLflow Server.

Адреса:

- Swagger UI: http://127.0.0.1:8000/docs
- MLflow UI: http://127.0.0.1:5000

Внутри Docker приложение обращается к MLflow по адресу `http://mlflow:5000`.

Для `app` и `db` настроены ограничения CPU и памяти, а также ротация логов.
Приложение запускается от непривилегированного пользователя.

### Запуск с уже зарегистрированными моделями

Если в сохранённых volumes уже есть модель `rentlens-price` и alias `champion`:

```bash
docker compose up -d --build
```

Приложение ждёт готовности PostgreSQL и MLflow, затем загружает модель.
Принимать запросы оно начинает после сообщения `Application startup complete`.

```bash
docker compose ps
docker compose logs --tail=50 app
```

### Первый запуск с пустым MLflow

Сначала запустите инфраструктуру:

```bash
docker compose up -d --build db mlflow-db mlflow
```

Затем подготовьте данные, обучите и зарегистрируйте модели по инструкции ниже.
После регистрации запустите приложение:

```bash
docker compose up -d --build app
```

При пустом Registry приложение не сможет завершить запуск: ему требуется зарегистрированная модель с alias `champion`.

### Остановка

```bash
docker compose down
```

Обычная остановка сохраняет данные в volumes.
Команда `docker compose down -v` удаляет volumes вместе с базами и артефактами.

## Подготовка и обучение моделей

Скачайте версию 100K датасета UCI и разместите исходный CSV:

```text
data/raw/apartments_for_rent_classified_100K.csv
```

Запускайте команды из корня проекта при работающем MLflow:

```bash
uv run python scripts/clean_data.py
uv run python scripts/eda_overview.py
uv run python scripts/eda_plots.py
uv run python scripts/log_eda.py
uv run python scripts/split_data.py
uv run python scripts/train_linear.py
uv run python scripts/train_forest.py
uv run python scripts/train_catboost.py
```

Каждое повторное обучение создаёт новый Run и новую сохранённую модель.

После обучения обновите `reports/selected_models.json`:
укажите новые `run_id`, `model_id`, `model_uri` и `validation_mae`
для выбранных запусков. Основная модель задаётся полем
`"primary_model": "RandomForestRegressor"`.

ID из этого файла привязаны к конкретному MLflow Server.
На новом сервере или после повторного обучения их необходимо обновить.

Затем выполните:

```bash
uv run python scripts/evaluate_best.py
uv run python scripts/register_models.py
```

Test используется для финальной оценки уже выбранной модели.
Подбор параметров выполняется по validation.

## MLflow и происхождение данных

Эксперименты:

- `rentlens-eda` — исследовательский анализ;
- `rentlens-training` — обучение и финальная тестовая проверка.

В MLflow сохраняются параметры, метрики, датасеты и артефакты.

Для датасетов фиксируются:

- **source** — источник данных, например путь к CSV;
- **digest** — вычисленный MLflow fingerprint датасета;
- **context** — назначение данных: training, validation или testing.

Lineage описывает связь между исходными данными, очищенным датасетом,
выборками, запуском обучения и сохранённой моделью.

Связи поддерживаются через логирование входных датасетов,
`metadata.json`, SHA-256 исходного CSV и ссылки на Run и модель.
MLflow не восстанавливает автоматически все преобразования данных.

В UI можно выбрать три запуска обучения и сравнить их
`validation_mae`, `validation_rmse` и `validation_r2`.

## Model Registry

Общее имя зарегистрированной модели: `rentlens-price`.

В текущем MLflow Server:

| Версия | Алгоритм | Alias |
|---|---|---|
| 1 | RandomForestRegressor | `champion` |
| 2 | CatBoostRegressor | `challenger` |

LinearRegression сохранена в эксперименте как базовая модель.

Рабочая модель выбирается через:

```text
models:/rentlens-price@champion
```

При запуске приложение получает конкретную версию через alias
и загружает её по номеру версии. Поэтому ответ API содержит
номер именно загруженной модели.

## API

### `POST /process`

Асинхронный endpoint прогнозирования месячной аренды.

Обязательное поле — `square_feet`.
Остальные признаки можно передать как `null` или пропустить:
пропуски обработает сохранённый preprocessing.

Пример:

```bash
curl -sS -X POST http://127.0.0.1:8000/process \
  -H "Content-Type: application/json" \
  -d '{
    "square_feet": 900,
    "bedrooms": 2,
    "bathrooms": 1,
    "latitude": 40.7128,
    "longitude": -74.0060,
    "cityname": "New York",
    "state": "NY",
    "pets_allowed": "Cats,Dogs"
  }'
```

Ответ текущего RandomForest:

```json
{
  "predicted_price": 4331.42,
  "currency": "USD",
  "price_type": "monthly",
  "model_name": "rentlens-price",
  "model_version": "1",
  "model_algorithm": "RandomForestRegressor"
}
```

Это прогноз для переданных параметров, а не цена реального объявления.

Предсказание выполняется в отдельном потоке.
Модель не загружается повторно при каждом запросе.

Коды ответа:

- `200` — прогноз получен;
- `422` — некорректные параметры;
- `503` — модель не загружена;
- `500` — ошибка предсказания.

### Health endpoints

| Endpoint | Назначение |
|---|---|
| `GET /healthz` | Проверка доступности приложения |
| `GET /api/v1/version` | Версия установленного пакета; текущая — `0.1.1` |
| `GET /api/v1/health` | Проверка соединения с PostgreSQL и времени ответа |

При недоступности PostgreSQL `/api/v1/health` возвращает `503`.
Внутренние детали ошибок записываются в логи.

## Переключение рабочей модели

Назначение `champion` версии 2:

```bash
uv run python - <<'PY'
import mlflow
from mlflow.tracking import MlflowClient

mlflow.set_tracking_uri("http://127.0.0.1:5000")
client = MlflowClient()
client.set_registered_model_alias("rentlens-price", "champion", "2")
PY
```

До перезапуска приложение продолжит использовать предыдущую модель.

```bash
docker compose restart app
docker compose logs --since=1m app
```

После завершения загрузки `/process` будет использовать CatBoost,
версию 2. Код endpoint менять не требуется.

Для возврата RandomForest выполните ту же команду назначения alias
с версией `"1"` и снова перезапустите приложение.

В текущей реализации переключение требует перезапуска и вызывает
кратковременную недоступность единственного экземпляра приложения.

Для обновления без простоя можно запускать новый экземпляр с выбранной
версией, проверять его готовность и затем переключать на него трафик.

## Проверки качества

```bash
uv run --group web ruff check .
uv run --group web ruff format --check .
uv run --group web python -m pytest \
  --cov=rentlens \
  --cov-report=term-missing \
  --cov-fail-under=90
```

Последняя локальная проверка:

- 18 тестов прошли;
- покрытие `rentlens` — 98,53%;
- покрытие `api/process.py` — 100%;
- Ruff lint прошёл.

Тесты проверяют health endpoints, успешное предсказание,
обработку пропусков и неверных параметров, ошибки модели,
однократную загрузку и выбор конкретной версии через alias.

В тестах PostgreSQL и загрузка модели подменяются тестовыми объектами.
Работающие внешние сервисы для unit-тестов не требуются.

## Pre-commit

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

Hooks проверяют оформление файлов, YAML, размер добавляемых файлов,
Ruff lint и форматирование.

Если hook изменил файл, добавьте исправление в Git перед повторным коммитом.

## CI/CD

`.github/workflows/ci.yml` запускает проверки при push в `main`
и Pull Request в `main`: установку зависимостей, Ruff lint,
проверку форматирования и тесты с порогом покрытия 90%.

`.github/workflows/cd.yml` запускается по тегам `vX.Y.Z`.
После проверок он собирает и публикует Docker-образ приложения в:

```text
ghcr.io/kamii86/rentlens
```

Используются теги версии, `latest` и `sha-*`.

Docker-образ содержит приложение и зависимости.
Обученные модели и данные MLflow хранятся отдельно.

## Работа с Git

Перед коммитом проверьте изменённые файлы:

```bash
git status --short
git diff
```

Не добавляйте `.env`, `.venv`, пароли, токены и локальные хранилища MLflow.

Для текущей работы используется ветка `homework-3`.
После проверки изменений создайте коммит и отправьте ветку:

```bash
git add .
git commit -m "feat: add MLflow training and rental prediction API"
git push -u origin homework-3
```

## Команда

Проект разрабатывается командой из трёх человек.
