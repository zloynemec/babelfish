# Local Translation Service

Локальный HTTP-сервис машинного перевода с подключаемыми движками-провайдерами.

## Цель MVP

Сделать отдельный сервис, который:

- выполняет перевод локально и не отправляет текст запросов перевода внешним сервисам;
- отдельно аннотирует URL, HTML или готовый текст через внешний ИИ-провайдер;
- не зависит от платных или квотируемых API перевода;
- не требует авторизации;
- предоставляет стабильный HTTP API;
- по умолчанию переводит текст с английского на указанный целевой язык через Argos Translate;
- позволяет явно выбрать Marian/CTranslate2 как альтернативный локальный движок;
- позволяет явно выбрать переводчик;
- позволяет передавать параметры конкретному переводчику;
- не привязывает API-контракт к одной библиотеке или модели.

## Выбранный стек

- Python 3.12+
- FastAPI
- Uvicorn
- Pydantic v2
- Argos Translate — первый и default provider
- MarianMT через CTranslate2 — второй provider
- pytest — тесты
- Docker — опционально, но предусмотрен с начала проекта

Почему Python: Argos Translate, Marian/CTranslate2 и большинство локальных ML-инструментов имеют нативную Python-интеграцию. Это позволяет не держать отдельный Python worker рядом с Node.js API.

## Основной API

### Аннотация контента

`POST /v1/annotate` принимает ровно один из трёх вариантов входа:

```json
{"url":"https://example.org/article"}
```

```json
{"html":"<main><p>Article content.</p></main>"}
```

```json
{"text":"Article content."}
```

Сервис извлекает основной текст из URL или HTML и формирует аннотацию на русском
в 2–3 предложениях. Готовый `text` передаётся модели без очистки. Это отдельная
функция с внешним ИИ-вызовом: подготовленный текст уходит выбранному провайдеру.
По умолчанию используется `iishko` с моделью `qwen3.8-flash`. Ключ задаётся
через `IISHKO_API_KEY` в окружении, а не в запросе. Также доступен отдельный
`annotator: "qwen_local"`: локальный Qwen3-4B Q4_K_M через llama.cpp. Его адрес
задаётся `QWEN_LOCAL_BASE_URL` (по умолчанию `http://127.0.0.1:8081/v1`),
имя модели — `QWEN_LOCAL_MODEL` (`qwen3-4b`). Провайдеры используют один и тот
же системный запрос. Если выбранный провайдер не готов, `/v1/annotate`
возвращает `503 annotator_unavailable`. `GET /v1/annotators` показывает
зарегистрированных аннотаторов и их готовность.

Локальную модель можно запустить отдельно от API:

```bash
brew install llama.cpp
mkdir -p models/qwen3-4b
python -c 'from huggingface_hub import hf_hub_download; hf_hub_download(repo_id="Qwen/Qwen3-4B-GGUF", filename="Qwen3-4B-Q4_K_M.gguf", local_dir="models/qwen3-4b")'
llama-server --model models/qwen3-4b/Qwen3-4B-Q4_K_M.gguf --alias qwen3-4b --host 127.0.0.1 --port 8081 --ctx-size 32768 --parallel 2 --gpu-layers 99 --reasoning off
```

Для CPU запуска параметр `--gpu-layers` можно убрать. API-сервис стартует и без
локальной модели; тогда `qwen_local` отображается как неготовый.

Существующий `/v1/translate` по-прежнему переводит локально. Подробности
контракта: [API-контракт](docs/03-api-contract.md).

### Перевод

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

## Marian/CTranslate2

Marian provider регистрируется автоматически под именем `marian`. Установите
оптимизированную модель `en -> ru` в пользовательское хранилище:

```bash
python scripts/install_marian_model.py --from en --to ru
```

Запрос с явным выбором provider:

```json
{
  "text": "A collection of media links about air quality research",
  "source_language": "en",
  "target_language": "ru",
  "translator": "marian"
}
```

Модель скачивается из Hugging Face, конвертируется в CTranslate2 с `int8`
quantization и хранится вне Git-репозитория. Подробнее:
[Marian/CTranslate2](docs/08-marian.md).

## Документация проекта

- [Требования MVP](docs/01-product-requirements.md)
- [Архитектура](docs/02-architecture.md)
- [API-контракт](docs/03-api-contract.md)
- [План разработки](docs/04-development-plan.md)
- [Тестирование и критерии готовности](docs/05-testing-and-acceptance.md)
- [Установка и запуск](docs/06-installation.md)
- [Подключение языков Argos](docs/07-argos-languages.md)
- [Marian/CTranslate2](docs/08-marian.md)
- [Аннотирование](docs/09-annotation-proposal.md)
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
│           ├── argos.py
│           └── marian.py
├── scripts/
│   ├── install_argos_model.py
│   └── install_marian_model.py
└── tests/
    ├── unit/
    └── integration/
```
