# Архитектура

## 1. Общая схема

```text
Consumer
   |
   | HTTP/JSON
   v
FastAPI routes
   |
   v
TranslationService
   |
   +---- TranslatorRegistry ----+
   |                            |
   v                            v
ArgosProvider          Future providers
                      - Marian/CTranslate2
                      - Ollama
                      - Bergamot adapter
```

Ключевой принцип: transport/API слой ничего не знает о Python API конкретного переводчика.

## 2. Слои

### API layer

Ответственность:

- HTTP routing;
- Pydantic request/response validation;
- request id;
- преобразование application errors в HTTP responses.

Не должен:

- загружать модели;
- импортировать Argos напрямую;
- выполнять provider-specific ветвление вида `if translator == ...`.

### Application service

`TranslationService`:

1. применяет default source language и default translator;
2. проверяет общие ограничения;
3. получает provider из registry;
4. вызывает provider;
5. измеряет duration;
6. формирует нормализованный результат.

### Translator registry

Хранит зарегистрированные provider instances по уникальному имени.

Минимальные операции:

```text
get(name)
list()
exists(name)
```

Registry создаётся на startup приложения через dependency/container factory.

### Provider layer

Каждый provider адаптирует конкретный движок к единому внутреннему контракту.

Предлагаемые domain types:

```python
@dataclass(frozen=True)
class ProviderTranslationRequest:
    text: str
    source_language: str
    target_language: str
    params: Mapping[str, Any]

@dataclass(frozen=True)
class ProviderTranslationResult:
    translation: str
    metadata: Mapping[str, Any]

@dataclass(frozen=True)
class ProviderCapabilities:
    supported_pairs: list[tuple[str, str]] | None
    accepts_params: bool

@dataclass(frozen=True)
class ProviderHealth:
    ready: bool
    detail: str | None = None
```

Интерфейс:

```python
class TranslatorProvider(Protocol):
    name: str

    def translate(self, request: ProviderTranslationRequest) -> ProviderTranslationResult:
        ...

    def capabilities(self) -> ProviderCapabilities:
        ...

    def health(self) -> ProviderHealth:
        ...
```

## 3. Argos provider

### MVP behavior

`ArgosProvider`:

- использует локально установленный пакет Argos Translate;
- выполняет inference локально и не отправляет переводимый текст наружу;
- может загружать публичные модели и служебные файлы в runtime;
- проверяет наличие нужной языковой пары;
- переводит текст;
- нормализует ошибки библиотеки.

### Model lifecycle

Воспроизводимый сценарий для production:

1. приложение/контейнер устанавливается;
2. оператор явно запускает `scripts/install_argos_model.py --from en --to ru`;
3. модель сохраняется локально;
4. сервис запускается;
5. provider обнаруживает установленную пару.

Runtime-загрузка из публичного model repository также допустима. Она не считается
внешним API перевода: после загрузки модели запросы обрабатываются локально и без
ограничений по числу переводов. Ни URL загрузки, ни её параметры не должны содержать
пользовательский текст.

## 4. Translator-specific params

Публичное поле:

```json
"translator_params": {}
```

Поток:

```text
HTTP JSON
 -> TranslateRequest.translator_params
 -> TranslationService
 -> ProviderTranslationRequest.params
 -> provider.validate_params(...)
 -> provider implementation
```

Для Argos в первой версии допускается не поддерживать никаких дополнительных параметров. Тогда `{}` корректен, а неизвестные ключи должны возвращать `invalid_translator_params`.

Будущий Marian provider сможет, например, принимать внутренние параметры beam/quantization только если они осмысленны для выбранной реализации. Не следует заранее включать такие поля в общий request schema.

## 5. Ошибки

Внутренние exception types:

```text
UnknownTranslatorError
TranslatorUnavailableError
UnsupportedLanguagePairError
InvalidTranslatorParamsError
TranslationTimeoutError
TranslationFailedError
```

API слой преобразует их в единый error envelope.

## 6. Liveness и readiness

### `/health/live`

Показывает, что процесс приложения жив и способен отвечать по HTTP.

Не требует установленной ML-модели.

### `/health/ready`

Проверяет как минимум default provider.

Если default provider не готов, endpoint возвращает HTTP 503.

Это позволяет контейнеру стартовать даже до установки модели, сохраняя корректную семантику readiness.

## 7. Синхронный inference

Большинство локальных движков выполняют синхронный CPU/GPU inference.

FastAPI route может быть `async`, но provider call не должен надолго блокировать event loop.

Для MVP использовать простой thread offload, например `anyio.to_thread.run_sync`.

Если измерения покажут, что отдельные движки плохо масштабируются в threads или требуют process isolation, это решается на provider/application уровне без изменения внешнего API.

## 8. Timeout

Application service должен применять общий configurable timeout.

Важно: отмена await по timeout не всегда физически прерывает CPU inference в worker thread. В MVP timeout прежде всего ограничивает время ожидания клиента и возвращает согласованную ошибку. Если жёсткое завершение inference станет обязательным, provider следует вынести в отдельный worker process.

## 9. Логирование

Рекомендуемый structured log event для успешного запроса:

```json
{
  "event": "translation.completed",
  "request_id": "...",
  "translator": "argos",
  "source_language": "en",
  "target_language": "ru",
  "text_length": 1234,
  "duration_ms": 87
}
```

Не логировать полный пользовательский текст по умолчанию.

## 10. Будущее масштабирование

Без изменения `/v1/translate` можно добавить:

- Marian/CTranslate2 provider;
- Ollama provider;
- automatic language detection перед provider selection;
- fallback policy;
- caching layer;
- batch endpoint;
- API key middleware;
- metrics `/metrics`;
- отдельные inference workers.

Все это вне MVP.
