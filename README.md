# RentLens

RentLens — сервис для оценки справедливой стоимости аренды жилья.

Проект позволяет сравнить цену объявления с ожидаемой рыночной стоимостью квартиры и определить, является ли предложение справедливым, переоценённым или выгодным.

## Возможности

На текущем этапе реализованы:

- REST API на FastAPI;
- проверка доступности приложения;
- получение версии приложения;
- проверка состояния PostgreSQL;
- асинхронное подключение к PostgreSQL;
- автоматические тесты API;
- проверка покрытия тестами;
- статический анализ кода с Ruff.

В дальнейшем планируется:

- оценка рыночной стоимости аренды с помощью ML-модели;
- сравнение цены объявления с прогнозируемой стоимостью;
- определение переоценённых и выгодных предложений;
- поиск похожих объектов;
- веб-интерфейс для работы с сервисом.

## Технологии

- Python 3.12
- FastAPI
- Uvicorn
- PostgreSQL
- SQLAlchemy
- asyncpg
- uv
- pytest
- pytest-asyncio
- pytest-cov
- httpx
- Ruff

## Структура проекта

```text
rentlens/
├── src/
│   └── rentlens/
│       ├── api/
│       │   ├── __init__.py
│       │   └── health.py
│       ├── __init__.py
│       ├── config.py
│       ├── database.py
│       ├── main.py
│       └── version.py
├── tests/
│   ├── __init__.py
│   └── test_health.py
├── .env.example
├── .gitignore
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

Если `uv` уже установлен, переходите к следующему шагу.

Инструкция по установке доступна в официальной документации uv.

### 3. Создание виртуального окружения

В проекте используется виртуальное окружение `venv`.

```bash
uv venv venv --python 3.12
```

Активируйте его.

macOS / Linux:

```bash
source venv/bin/activate
```

Windows PowerShell:

```powershell
venv\Scripts\Activate.ps1
```

### 4. Установка зависимостей

Установите зависимости проекта, включая группы разработки и web:

```bash
UV_PROJECT_ENVIRONMENT=venv uv sync --all-groups
```

## Настройка PostgreSQL

Для локального запуска необходим PostgreSQL.

Создайте базу данных:

```bash
createdb rentlens
```

> Команда может отличаться в зависимости от способа установки PostgreSQL и операционной системы.

Например, при установке PostgreSQL 17 через Homebrew:

```bash
brew services start postgresql@17
```

Создание базы:

```bash
/opt/homebrew/opt/postgresql@17/bin/createdb rentlens
```

## Переменные окружения

Создайте в корне проекта файл `.env`.

В качестве шаблона используйте `.env.example`.

Пример:

```env
DATABASE_URL=postgresql+asyncpg://username@localhost:5432/rentlens
```

Замените `username` на имя пользователя PostgreSQL в вашей системе.

Файл `.env` содержит локальные настройки и не должен добавляться в Git.

## Запуск приложения

Убедитесь, что:

1. виртуальное окружение активировано;
2. PostgreSQL запущен;
3. база данных `rentlens` создана;
4. файл `.env` настроен.

Запустите FastAPI:

```bash
python -m uvicorn rentlens.main:app --reload
```

После запуска приложение доступно по адресу:

```text
http://127.0.0.1:8000
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## API

### `GET /healthz`

Liveness-проверка приложения.

Endpoint проверяет, что само FastAPI-приложение запущено и способно отвечать на запросы.

Пример ответа:

```json
{
  "status": "ok"
}
```

### `GET /api/v1/version`

Возвращает текущую версию приложения.

Пример ответа:

```json
{
  "version": "0.1.0"
}
```

Версия берётся из метаданных проекта.

### `GET /api/v1/health`

Проверяет доступность PostgreSQL и возвращает информацию о состоянии компонента.

Если PostgreSQL доступен:

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

Если PostgreSQL недоступен:

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

Запуск всех тестов:

```bash
pytest
```

Подробный вывод:

```bash
pytest -v
```

Запуск тестов с отчётом о покрытии:

```bash
pytest --cov=rentlens --cov-report=term-missing
```

Проверка минимального покрытия 90%:

```bash
pytest --cov=rentlens --cov-report=term-missing --cov-fail-under=90
```

На текущем этапе тестами проверяются:

- `/healthz`;
- `/api/v1/version`;
- успешное подключение `/api/v1/health` к PostgreSQL;
- недоступность PostgreSQL и возврат `503`.

Для проверки сценариев PostgreSQL в тестах используется подмена подключения, поэтому тесты не требуют ручного включения и выключения базы данных.

## Проверка качества кода

Запуск Ruff:

```bash
ruff check .
```

Автоматическое исправление поддерживаемых ошибок:

```bash
ruff check . --fix
```

Проверка форматирования:

```bash
ruff format --check .
```

Форматирование:

```bash
ruff format .
```

## Проверка перед commit

Перед отправкой изменений рекомендуется выполнить:

```bash
ruff check . && pytest --cov=rentlens --cov-report=term-missing --cov-fail-under=90
```

После добавления автоматической проверки форматирования также рекомендуется выполнять:

```bash
ruff format --check .
```

## Работа с Git

Перед началом работы получите последние изменения:

```bash
git pull
```

Для новой задачи создавайте отдельную ветку:

```bash
git switch -c feature/<task-name>
```

Например:

```bash
git switch -c feature/docker
```

После завершения работы:

```bash
git add .
git commit -m "feat: describe changes"
git push -u origin feature/<task-name>
```

После push создайте Pull Request в `main`.

Не добавляйте в репозиторий:

- `.env`;
- виртуальное окружение `venv`;
- пароли и токены;
- локальные файлы IDE;
- другие секреты и локальные настройки.

## Текущее состояние проекта

Реализовано:

- [x] базовая структура проекта;
- [x] FastAPI;
- [x] PostgreSQL;
- [x] асинхронное подключение к БД;
- [x] `/healthz`;
- [x] `/api/v1/version`;
- [x] `/api/v1/health`;
- [x] обработка недоступности PostgreSQL;
- [x] тесты API;
- [x] coverage;
- [x] Ruff.

В работе:

- [ ] Dockerfile;
- [ ] Docker Compose;
- [ ] pre-commit;
- [ ] CI;
- [ ] CD;
- [ ] Container Registry;
- [ ] структурированное логирование;
- [ ] финальная документация и проверка полного pipeline.

## Команда

Проект разрабатывается командой из трёх человек.

Основная разработка ведётся через отдельные Git-ветки и Pull Request.