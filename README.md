# RentLens

RentLens — учебный шаблон асинхронного backend-сервиса на FastAPI.

Проект используется как базовая инфраструктурная заготовка для Python-сервисов: приложение работает с PostgreSQL, имеет health-check endpoints, автоматические тесты, контейнеризацию, pre-commit, CI/CD и публикацию Docker-образов.

## Возможности

На текущем этапе реализованы:

- REST API на FastAPI;
- асинхронная работа приложения;
- подключение к PostgreSQL через SQLAlchemy и asyncpg;
- liveness health-check приложения;
- end-to-end health-check PostgreSQL;
- получение версии приложения;
- автоматические тесты API;
- проверка покрытия тестами;
- статический анализ и форматирование кода через Ruff;
- Dockerfile;
- Docker Compose для приложения и PostgreSQL;
- healthcheck PostgreSQL в Docker Compose;
- Docker volumes;
- ограничения CPU и памяти контейнеров;
- ротация Docker-логов;
- pre-commit hooks;
- CI через GitHub Actions;
- CD через GitHub Actions;
- публикация Docker-образов в GitHub Container Registry;
- версионирование Docker-образов;
- логирование приложения.

## Технологии

- Python 3.12
- FastAPI
- Uvicorn
- PostgreSQL 17
- SQLAlchemy
- asyncpg
- uv
- pytest
- pytest-asyncio
- pytest-cov
- httpx
- Ruff
- pre-commit
- Docker
- Docker Compose
- GitHub Actions
- GitHub Container Registry

## Структура проекта

```text
rentlens/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── cd.yml
├── src/
│   └── rentlens/
│       ├── api/
│       │   ├── __init__.py
│       │   └── health.py
│       ├── __init__.py
│       ├── config.py
│       ├── database.py
│       ├── logging_config.py
│       ├── main.py
│       └── version.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   └── test_health.py
├── .dockerignore
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── Dockerfile
├── compose.yaml
├── pyproject.toml
├── uv.lock
└── README.md
```

## Установка

### 1. Клонирование репозитория

```bash
git clone git@github.com:kamii86/rentlens.git
cd rentlens
```

### 2. Установка uv

Проверьте, установлен ли `uv`:

```bash
uv --version
```

Если `uv` не установлен:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

После установки может потребоваться перезапустить терминал или выполнить:

```bash
source $HOME/.local/bin/env
```

### 3. Установка зависимостей

```bash
uv sync --all-groups
```

Команда создаёт виртуальное окружение `.venv` и устанавливает все зависимости проекта.

Группа `web` содержит зависимости, необходимые приложению во время работы.

Группа `dev` содержит инструменты разработки, тестирования и проверки качества кода.

## Переменные окружения

Для локального запуска приложение использует переменную:

```env
DATABASE_URL=postgresql+asyncpg://username@localhost:5432/rentlens
```

Создайте в корне проекта файл `.env` на основе `.env.example`.

Файл `.env` содержит локальные настройки и не должен добавляться в Git.

При запуске через Docker Compose строка подключения к PostgreSQL передаётся контейнеру приложения автоматически.

## Локальный запуск

Для локального запуска вне Docker необходимо:

1. установить зависимости;
2. запустить PostgreSQL;
3. создать базу данных;
4. настроить `.env`.

Запуск приложения:

```bash
uv run uvicorn rentlens.main:app --reload
```

После запуска приложение доступно по адресу:

```text
http://127.0.0.1:8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## Запуск через Docker Compose

Для запуска приложения и PostgreSQL:

```bash
docker compose up --build -d
```

Docker Compose создаёт два сервиса:

```text
app
↓
FastAPI

db
↓
PostgreSQL
```

Приложение ожидает успешного healthcheck PostgreSQL перед запуском.

Проверить состояние контейнеров:

```bash
docker compose ps
```

Посмотреть логи приложения:

```bash
docker compose logs app
```

Остановить контейнеры:

```bash
docker compose down
```

Данные PostgreSQL сохраняются в Docker volume и не удаляются при обычном пересоздании контейнера.

## API

### `GET /healthz`

Быстрая liveness-проверка приложения.

Endpoint проверяет только то, что FastAPI запущен и отвечает.

Пример:

```json
{
  "status": "ok"
}
```

### `GET /api/v1/version`

Возвращает текущую версию приложения.

Пример:

```json
{
  "version": "0.1.0"
}
```

Версия берётся из метаданных установленного Python-пакета.

### `GET /api/v1/health`

End-to-end health-check.

Endpoint проверяет соединение с PostgreSQL, получает её версию и измеряет время ответа.

Успешный ответ:

```json
{
  "status": "ok",
  "components": {
    "postgresql": {
      "status": "ok",
      "version": "PostgreSQL ...",
      "response_time_ms": 1.23
    }
  }
}
```

HTTP status:

```text
200 OK
```

Если PostgreSQL недоступна:

```json
{
  "status": "error",
  "components": {
    "postgresql": {
      "status": "error",
      "version": null,
      "response_time_ms": 15.09
    }
  }
}
```

HTTP status:

```text
503 Service Unavailable
```

## Тестирование

Запуск тестов:

```bash
uv run python -m pytest
```

Запуск тестов с отчётом о покрытии:

```bash
uv run python -m pytest --cov=rentlens --cov-report=term-missing
```

Проверка минимального покрытия 90%:

```bash
uv run python -m pytest \
  --cov=rentlens \
  --cov-report=term-missing \
  --cov-fail-under=90
```

На текущем этапе тестами проверяются:

- `/healthz`;
- `/api/v1/version`;
- успешная проверка PostgreSQL;
- недоступность PostgreSQL;
- возврат HTTP `503` при ошибке БД.

В тестах подключение к PostgreSQL подменяется тестовыми объектами, поэтому для unit-тестов настоящая база данных не требуется.

## Ruff

Проверка кода:

```bash
uv run ruff check .
```

Автоматическое исправление поддерживаемых ошибок:

```bash
uv run ruff check . --fix
```

Проверка форматирования:

```bash
uv run ruff format --check .
```

Форматирование:

```bash
uv run ruff format .
```

## Pre-commit

В проекте настроен pre-commit.

Установка Git hook после клонирования проекта:

```bash
uv run pre-commit install
```

Запуск всех проверок вручную:

```bash
uv run pre-commit run --all-files
```

Перед каждым коммитом автоматически выполняются:

- удаление лишних пробелов;
- проверка конца файлов;
- проверка больших файлов;
- проверка YAML;
- Ruff lint;
- Ruff format.

Если проверка автоматически изменила файл, его необходимо снова добавить через `git add` и повторить commit.

## Docker

Docker-образ приложения собирается на основе:

```text
python:3.12-slim
```

Для установки зависимостей используется `uv`.

Приложение внутри контейнера запускается не от пользователя `root`.

Локальная сборка:

```bash
docker build -t rentlens .
```

## Docker Compose

В Compose используются сервисы:

```text
app
db
```

Для PostgreSQL настроены:

- persistent volume;
- healthcheck;
- автоматический restart;
- ограничение ресурсов;
- ротация логов.

Для приложения настроены:

- сборка из Dockerfile;
- ожидание healthy PostgreSQL;
- порт `8000`;
- ограничение ресурсов;
- ротация логов.

Для каждого контейнера установлено ограничение:

```text
CPU: 1
RAM: 512 MB
```

Docker-логи ограничены:

```text
максимальный размер файла: 10 MB
максимальное количество файлов: 3
```

## Логирование

В приложении используется стандартный модуль `logging`.

Пример успешного health-check:

```text
time=2026-10-02 10:55:49,983 level=INFO logger=rentlens.api.health message=postgresql_healthcheck_success response_time_ms=22.68
```

При ошибке PostgreSQL записывается ERROR-лог с traceback.

Пользователю внутренние детали ошибки не возвращаются.

## CI

CI реализован через GitHub Actions.

Workflow:

```text
.github/workflows/ci.yml
```

CI запускается:

- при push в `main`;
- при Pull Request в `main`.

Pipeline выполняет:

```text
checkout
↓
Python 3.12
↓
uv
↓
установка зависимостей
↓
Ruff lint
↓
Ruff format check
↓
pytest
↓
coverage >= 90%
```

Если хотя бы одна проверка завершается ошибкой, CI pipeline падает.

## CD

CD реализован через GitHub Actions.

Workflow:

```text
.github/workflows/cd.yml
```

CD запускается при push Git-тега формата:

```text
vX.Y.Z
```

Например:

```text
v0.1.0
```

Pipeline:

```text
Git tag
↓
проверки кода
↓
тесты
↓
Docker build
↓
GitHub Container Registry
```

Для публикации используется GitHub Container Registry:

```text
ghcr.io/kamii86/rentlens
```

Для одного Docker-образа создаются несколько тегов.

Например для релиза `v0.1.0`:

```text
ghcr.io/kamii86/rentlens:0.1.0
ghcr.io/kamii86/rentlens:latest
ghcr.io/kamii86/rentlens:sha-<commit>
```

Используются три типа тегов:

- `0.1.0` — версия приложения;
- `latest` — последний опубликованный релиз;
- `sha-*` — точная привязка Docker-образа к Git-коммиту.

CD запускается только для release-тегов, чтобы не публиковать новый Docker-образ после каждого промежуточного коммита.

## Выпуск новой версии

Перед выпуском новой версии необходимо изменить версию приложения в:

```text
pyproject.toml
```

Например:

```toml
version = "0.1.1"
```

После проверки и commit создаётся Git tag:

```bash
git tag v0.1.1
```

Тег отправляется на GitHub:

```bash
git push origin v0.1.1
```

После этого автоматически запускается CD pipeline и публикуется новый Docker-образ.

## Работа с Git

Перед началом работы получите последние изменения:

```bash
git pull
```

Для новой задачи рекомендуется создавать отдельную ветку:

```bash
git switch -c feature/<task-name>
```

После завершения работы:

```bash
git add .
git commit -m "feat: describe changes"
git push -u origin feature/<task-name>
```

После push можно создать Pull Request в `main`.

Не добавляйте в репозиторий:

- `.env`;
- `.venv`;
- пароли;
- токены;
- локальные настройки IDE;
- другие секреты.

## Текущее состояние проекта

Реализовано:

- [x] GitHub-репозиторий;
- [x] управление проектом через uv;
- [x] разделение зависимостей `web` и `dev`;
- [x] Ruff;
- [x] асинхронное FastAPI-приложение;
- [x] PostgreSQL;
- [x] `/healthz`;
- [x] `/api/v1/version`;
- [x] `/api/v1/health`;
- [x] обработка недоступности PostgreSQL;
- [x] тесты API;
- [x] coverage выше 90%;
- [x] Dockerfile;
- [x] Docker Compose;
- [x] Docker volumes;
- [x] healthcheck PostgreSQL;
- [x] resource limits;
- [x] ротация Docker-логов;
- [x] pre-commit;
- [x] CI;
- [x] CD;
- [x] GitHub Container Registry;
- [x] версионирование Docker-образов;
- [x] логирование приложения.

## Команда

Проект разрабатывается командой из трёх человек.
