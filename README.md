# Local Translation Service

Локальный HTTP-сервис машинного перевода с подключаемыми движками-провайдерами.

## Цель MVP

Сделать отдельный сервис, который:

- выполняет перевод локально и не отправляет пользовательский текст внешним сервисам;
- не зависит от платных или квотируемых API перевода;
- не требует авторизации;
- предоставляет стабильный HTTP API;
- по умолчанию переводит текст с английского на указанный целевой язык через Argos Translate;
- позволяет явно выбрать переводчик;
- позволяет передавать параметры конкретному переводчику;
- не привязывает API-контракт к одной библиотеке или модели.

## Выбранный стек

- Python 3.12+
- FastAPI
- Uvicorn
- Pydantic v2
- Argos Translate — первый и default provider
- pytest — тесты
- Docker — опционально, но предусмотрен с начала проекта

Почему Python: Argos Translate, Marian/CTranslate2 и большинство локальных ML-инструментов имеют нативную Python-интеграцию. Это позволяет не держать отдельный Python worker рядом с Node.js API.

## Основной API

Минимальный запрос:

```http
POST /v1/translate
Content-Type: application/json
```

```json
{
  "text": "The spacecraft entered orbit.",
  "target_language": "ru"
}
```

Расширенный запрос:

```json
{
  "text": "The spacecraft entered orbit.",
  "target_language": "ru",
  "source_language": "en",
  "translator": "argos",
  "translator_params": {}
}
```

Пример ответа:

```json
{
  "translation": "Космический аппарат вышел на орбиту.",
  "source_language": "en",
  "target_language": "ru",
  "translator": "argos",
  "metadata": {
    "duration_ms": 42
  }
}
```

## Значения по умолчанию

- `source_language`: `en`
- `translator`: `argos`
- авторизация: отсутствует
- загрузка моделей и служебных файлов: разрешена

Все значения должны быть настраиваемыми через environment variables.

## API documentation

После запуска сервиса интерактивная документация Scalar доступна по адресу
`http://localhost:8000/docs`. Исходная OpenAPI-схема доступна на
`http://localhost:8000/openapi.json`.

## Установка

Краткий запуск из клонированного репозитория:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python scripts/install_argos_model.py --from en --to ru
uvicorn translation_service.main:app --host 0.0.0.0 --port 8000
```

Полная инструкция для Linux, macOS и Windows: [установка и запуск](docs/06-installation.md).

## Argos Translate

Установите зависимости проекта, затем установите нужную языковую модель:

```bash
python -m pip install -e '.[dev]'
python scripts/install_argos_model.py --from en --to ru
```

После установки модели запустите сервис:

```bash
uvicorn translation_service.main:app --host 0.0.0.0 --port 8000
```

Скрипт загружает публичную модель, но количество переводов после установки ничем
не квотируется: inference выполняется локально. Argos также может загрузить
необходимые служебные файлы при первом запросе. Пользовательский текст при этом
не отправляется наружу.

Если среда не имеет доступа к интернету, можно передать заранее скачанные файлы:

```bash
python scripts/install_argos_model.py \
  --from en \
  --to ru \
  --model-file /path/to/translate-en_ru.argosmodel \
  --sbd-model-file /path/to/en.onnx
```

## Документация проекта

- [Требования MVP](docs/01-product-requirements.md)
- [Архитектура](docs/02-architecture.md)
- [API-контракт](docs/03-api-contract.md)
- [План разработки](docs/04-development-plan.md)
- [Тестирование и критерии готовности](docs/05-testing-and-acceptance.md)
- [Установка и запуск](docs/06-installation.md)
- [Подключение языков Argos](docs/07-argos-languages.md)
- [OpenAPI](openapi.yaml)
- [Инструкции для Codex](AGENTS.md)

## Структура репозитория

```text
.
├── AGENTS.md
├── README.md
├── openapi.yaml
├── pyproject.toml
├── .env.example
├── src/
│   └── translation_service/
│       ├── main.py
│       ├── api/
│       │   ├── routes_health.py
│       │   ├── routes_translate.py
│       │   └── routes_translators.py
│       ├── core/
│       │   ├── config.py
│       │   ├── errors.py
│       │   └── logging.py
│       ├── domain/
│       │   ├── models.py
│       │   └── provider.py
│       ├── services/
│       │   ├── registry.py
│       │   └── translation.py
│       └── providers/
│           └── argos.py
├── scripts/
│   └── install_argos_model.py
└── tests/
    ├── unit/
    └── integration/
```
