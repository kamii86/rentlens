
# RentLens

RentLens — учебный сервис прогнозирования месячной стоимости аренды квартир в США.

Пользователь передаёт параметры квартиры в API, получает идентификатор задачи и позже запрашивает прогноз аренды по этому идентификатору. Вычисления выполняет отдельный воркер через RabbitMQ.

Проект включает подготовку данных, EDA, обучение и сравнение моделей, отслеживание экспериментов в MLflow, Model Registry и асинхронный API на FastAPI.

## Возможности

- очистка датасета и отчёт об исключённых объявлениях;
- исследовательский анализ данных с графиками;
- разделение данных на train, validation и test;
- обучение LinearRegression, RandomForestRegressor и CatBoostRegressor;
- сохранение параметров, метрик, датасетов и артефактов в MLflow;
- регистрация моделей и выбор рабочей версии через alias `champion`;
- загрузка модели из MLflow Registry один раз при запуске воркера;
- асинхронные `POST /api/v1/tasks` и `GET /api/v1/tasks/{task_id}`;
- ограниченная очередь RabbitMQ, backpressure, повторные попытки и DLQ;
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
pandas, matplotlib, scikit-learn, CatBoost, MLflow 3.5.1, FastStream,
RabbitMQ, aio-pika, Testcontainers, uv, pytest, httpx, Ruff, pre-commit, Docker, GitHub Actions и GHCR.

## Основные файлы

| Файл или папка | Назначение |
|---|---|
| `src/rentlens/main.py` | Создание FastAPI и подключение к RabbitMQ |
| `src/rentlens/api/process.py` | Валидация параметров и загрузка модели из MLflow |
| `src/rentlens/api/health.py` | Проверки состояния и версия приложения |
| `src/rentlens/api/tasks.py` | Создание задач и получение их статуса |
| `src/rentlens/worker.py` | FastStream-воркер с подтверждениями и повторными попытками |
| `src/rentlens/task_broker.py` | RabbitMQ, издатель и обработка переполнения |
| `src/rentlens/task_config.py` | Настройки очереди и concurrency |
| `src/rentlens/task_store.py` | Сохранение статуса и идемпотентность в PostgreSQL |
| `src/rentlens/batch_source.py` | Генератор задач с замедлением источника |
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
| `compose.yaml` | Базовая инфраструктура |
| `compose.override.yaml` | RabbitMQ, worker и настройки для ДЗ №4 |
| `measurements/` | CSV, логи экспериментов и пять графиков |
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

Для ДЗ №4 используются шесть сервисов:

| Сервис | Назначение |
|---|---|
| `app` | FastAPI, порт 8000 |
| `db` | PostgreSQL приложения |
| `mlflow` | Tracking Server и Model Registry, порт 5000 |
| `mlflow-db` | PostgreSQL для метаданных MLflow |
| `rabbitmq` | Очереди задач, DLQ и веб-интерфейс (порт 15672) |
| `worker` | ML-инференс отдельно от FastAPI |

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

API подключается к PostgreSQL и RabbitMQ. Отдельный воркер загружает модель `rentlens-price@champion` из MLflow при запуске.
До отправки задач проверьте готовность сервисов, в том числе воркера.

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
docker compose up -d --build app worker
```

При пустом Registry воркер не сможет начать инференс: ему требуется зарегистрированная модель с alias `champion`.

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

При запуске воркер разрешает alias в конкретную версию модели и загружает её в память. Для перехода на другую версию воркер необходимо перезапустить.

## API

### `POST /api/v1/tasks`

Отправляет задачу в RabbitMQ и возвращает `202 Accepted` с `task_id` и ссылкой для проверки статуса. Обязателен `square_feet`; остальные признаки необязательны.

```bash
curl -i -X POST http://127.0.0.1:8000/api/v1/tasks \
  -H 'Content-Type: application/json' \
  -d '{"square_feet":900,"bedrooms":2,"bathrooms":1,"latitude":40.7128,"longitude":-74.006,"cityname":"New York","state":"NY","pets_allowed":"Cats,Dogs"}'
```

Ответ содержит статус `ACCEPTED`, идентификатор `task_id` и `status_url`. При переполнении очереди или недоступности RabbitMQ сервис отвечает `503 Service Unavailable` с заголовком `Retry-After`. Некорректные параметры вызывают `422`.

### `GET /api/v1/tasks/{task_id}`

Возвращает текущий статус `PENDING`, `PROCESSING`, `COMPLETED` или `FAILED`, число попыток, а после успешного инференса — `predicted_price`. Для неизвестного идентификатора возвращает `404`.

```bash
curl http://127.0.0.1:8000/api/v1/tasks/ЗАМЕНИТЕ_НА_TASK_ID
```

Предсказание выполняется воркером и не блокирует event loop FastAPI.

### Health endpoints

| Endpoint | Назначение |
|---|---|
| `GET /healthz` | Проверка доступности приложения |
| `GET /api/v1/version` | Версия установленного пакета; текущая — `0.1.1` |
| `GET /api/v1/health` | Проверка соединения с PostgreSQL и времени ответа |

При недоступности PostgreSQL `/api/v1/health` возвращает `503`.
Внутренние детали ошибок записываются в логи.

## Переключение рабочей модели

Модель выбирается по alias `champion` при старте воркера. После назначения alias на другую версию нужно перезапустить **воркер**, а не API:

```bash
docker compose restart worker
docker compose logs --tail=50 worker
```

Уже выполняемые задачи при остановке воркера завершаются в рамках graceful shutdown, а при аварийной остановке неподтверждённые сообщения RabbitMQ могут быть доставлены повторно.

## Противодавление (backpressure) — домашняя работа №4

### Архитектура

`Client → FastAPI → RabbitMQ → FastStream worker → MLflow model → PostgreSQL`.

Воркер загружает модель из `MLflow Model Registry` по alias `champion` один раз при старте. Задержка инференса задаётся параметром `INFERENCE_SECONDS`; предсказание модели вызывается через `asyncio.to_thread`, чтобы не блокировать цикл событий.

Очередь в режиме `bounded` использует `x-max-length=10` и `x-overflow=reject-publish`. Публикация выполняется с подтверждениями брокера (publisher confirms). Каждый воркер использует `prefetch_count=1`, то есть одновременно получает не более одной неподтверждённой задачи. `WORKER_CONCURRENCY=1` ограничивает параллельность внутри воркера.

Если RabbitMQ отклоняет публикацию, пакетный источник сохраняет тот же `task_id`, экспоненциально увеличивает паузу от 0,1 до 2 секунд и повторяет попытку. HTTP API вместо накопления запросов возвращает `503` и `Retry-After` (в базовой конфигурации — 2 секунды). В БД не создаётся `PENDING` для отклонённого брокером запроса.

Подтверждение `ack` отправляется только после сохранения результата. При временной ошибке используется `nack(requeue=True)`. После трёх неуспешных попыток задача получает статус `FAILED`, сообщение отклоняется без повторной постановки и попадает в `rentlens.dlq` через DLX. Уникальный `task_id` и условные обновления в PostgreSQL предотвращают повторную фиксацию уже завершённой задачи. Для остановки предусмотрен graceful shutdown.

### Параметры

| Переменная | Значение при эксперименте | Назначение |
|---|---:|---|
| `QUEUE_MODE` | `bounded` / `unbounded` | Режим очереди |
| `QUEUE_LIMIT` | `10` | Максимум готовых сообщений в ограниченной очереди |
| `PREFETCH_COUNT` | `1` | Максимум неподтверждённых сообщений на воркер |
| `WORKER_CONCURRENCY` | `1` | Параллелизм инференса внутри воркера |
| `INFERENCE_SECONDS` | `2` | Искусственная задержка обработки |
| `MAX_ATTEMPTS` | `3` | Порог отправки неудачной задачи в DLQ |

### Запуск и проверка

```bash
docker compose up -d --build
docker compose ps
docker compose exec rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged consumers
```

RabbitMQ Management UI: http://127.0.0.1:15672 (`rentlens` / `rentlens` в локальном Docker Compose). Swagger: http://127.0.0.1:8000/docs.

Запуск источника на 40 задач с хост-машины:

```bash
RABBITMQ_URL=amqp://rentlens:rentlens@127.0.0.1:5672/ BATCH_COUNT=40 uv run python -m rentlens.batch_source
```

Сравнение двух воркеров выполняется после запуска и готовности обоих контейнеров, например `docker compose up -d --scale worker=2 worker`. Чтобы вернуться к одному воркеру: `docker compose up -d --scale worker=1 worker`. Для режима без ограничения задайте `QUEUE_MODE=unbounded` в окружении **всех** участников и перезапустите сервисы; после эксперимента верните `bounded`.

### Эксперименты

Во всех трёх сценариях источник отправлял 40 задач, задержка инференса составляла около двух секунд, `prefetch_count=1` на воркер. Замеры хранятся в `measurements/`.

| Сценарий | Принято | Отклонений при публикации | Время отправки 40 задач | Скорость источника | Пик `ready` | Пик `unacked` |
|---|---:|---:|---:|---:|---:|---:|
| Ограниченная, 1 воркер | 40 | 125 | 60,26 с | 0,66/с | 10 | 1 |
| Ограниченная, 2 воркера | 40 | 61 | 29,44 с | 1,36/с | 10 | 2 |
| Неограниченная, 1 воркер | 40 | 0 | ≈0,04 с | ≈1000/с | 40 | 1 |

В таблице указано **время отправки задач источником**, а не время завершения предсказаний. В неограниченном режиме источник отправляет сообщения почти мгновенно, но задачи продолжают ожидать обработки. В ограниченном режиме очередь удерживается в пределах десяти готовых сообщений, а источник замедляется под нагрузкой. Второй воркер увеличил наблюдаемую скорость отправки с 0,66 до 1,36 задачи/с (примерно в 2,05 раза).

Пиковая память воркеров в ограниченном режиме: около 590 МБ для одного и суммарно около 1178 МБ для двух. В неограниченном сценарии наблюдалось около 655 МБ у одного воркера и около 253 МБ у RabbitMQ. Эти значения зависят от загрузки модели и момента измерения; не являются изолированной оценкой стоимости одной задачи.

В общей выборке из 322 завершённых задач время `finished_at - created_at` составило в среднем 2,10 с, минимум 2,03 с, максимум 20,11 с. Максимум относится к отдельному испытанию с 20-секундной задержкой. Для задач, созданных источником, `created_at` фиксируется при начале обработки воркером; для задач HTTP API учитывается время после регистрации задачи, поэтому эти значения нельзя считать полностью сопоставимой метрикой задержки ожидания в очереди.

### Графики

Глубина очереди во времени:

![Глубина очереди](measurements/plots/queue_depth.png)

Потребление памяти RabbitMQ:

![Память RabbitMQ](measurements/plots/rabbitmq_memory.png)

Потребление памяти воркеров:

![Память воркеров](measurements/plots/worker_memory.png)

Прогресс и скорость отправки задач источником:

![Скорость источника](measurements/plots/source_progress.png)

Время выполнения отдельных задач, упорядоченных по созданию:

![Время выполнения задач](measurements/plots/task_durations.png)

Графики строятся из CSV и логов экспериментов:

```bash
uv run python scripts/plot_experiments.py
uv run python scripts/plot_task_durations.py
```

### Проверки отказов

Ручными испытаниями проверены `503` и `Retry-After` при переполнении, отсутствие оставшихся `PENDING` после отказа, отправка некорректной задачи в DLQ после трёх попыток, идемпотентность повторной доставки и graceful shutdown в ходе длительного инференса. Автоматические проверки включают `TestRabbitBroker` и интеграционный тест переполнения с настоящим RabbitMQ через `Testcontainers`.

## Проверки качества

```bash
uv run ruff check .
uv run ruff format --check .
DATABASE_URL="postgresql+asyncpg://rentlens:rentlens@localhost:5432/rentlens" uv run pytest --cov=rentlens --cov-report=term-missing --cov-fail-under=90
```

Последняя локальная проверка: **57 passed**, покрытие **94,75%**, обе проверки Ruff пройдены. Предупреждение Testcontainers связано с устаревающим декоратором внутри библиотеки, не с провалом теста.

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

Работа ведётся в ветке `homework-4`. Перед коммитом следует проверить `git status --short` и `git diff --check`. Не добавляйте `.env`, `.venv`, пароли, токены и локальные хранилища MLflow.

```bash
git add README.md compose.override.yaml measurements scripts/monitor.py scripts/plot_experiments.py scripts/plot_task_durations.py src/rentlens tests pyproject.toml uv.lock
git diff --cached --stat
git commit -m "feat: add RabbitMQ backpressure pipeline"
git push -u origin homework-4
```

## Команда

Проект разрабатывается командой из трёх человек.
