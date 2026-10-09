# Архитектура

## 1. Общая схема

Для отдельного метода `/v1/annotate` используется параллельная цепочка:

```text
HTTP route -> AnnotationService -> ContentPreparer -> AnnotatorRegistry
                                           |                 |
                                           +-- URL/HTML/text +-- IishkoProvider
                                                             +-- QwenLocalProvider -> llama.cpp
```

`AnnotationService` подготавливает содержимое и вызывает provider; `IishkoProvider`
отвечает за внешний API модели, `QwenLocalProvider` — за локальный llama.cpp сервер.
Реестр аннотаторов отделён от реестра
переводчиков. Текст из `/v1/annotate` разрешено отправлять внешнему provider;
ограничение локального inference для `/v1/translate` сохраняется.

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
ArgosProvider          MarianProvider          Future providers
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

## 4. Marian/CTranslate2 provider

`MarianProvider`:

- использует модели MarianMT/OPUS-MT, заранее конвертированные в формат CTranslate2;
- обнаруживает модели по manifest-файлам в `MARIAN_MODELS_DIR`;
- загружает конкретную языковую пару лениво при первом переводе;
- кэширует runtime в памяти процесса;
- использует Hugging Face tokenizer только из локального каталога модели;
- выполняет inference через `ctranslate2.Translator` без сетевых запросов.

Вход ограничен токенным лимитом tokenizer, но не более 1024 токенов, включая
служебные токены. Превышение возвращает `413 text_too_large` без усечения.
Автоматическое усечение CTranslate2 отключено. Генерация ограничена 1024 токенами;
ответ без EOS отклоняется как `500 translation_failed`.

Структура установленной модели:

```text
MARIAN_MODELS_DIR/
└── en-ru/
    ├── babelfish-model.json
    ├── model/
    │   ├── config.json
    │   ├── model.bin
    │   └── ...
    └── tokenizer/
        └── ...
```

Установщик `scripts/install_marian_model.py` загружает Transformers-модель,
сохраняет tokenizer и конвертирует веса с настраиваемой quantization. Эти файлы
находятся вне Git-репозитория.

## 5. Translator-specific params

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

В первой версии Marian provider, как и Argos, принимает только пустой объект `{}`.
Compute type задаётся конфигурацией процесса, а quantization — при установке модели.
Не следует заранее включать эти параметры в общий request schema.

## 6. Ошибки

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

## 7. Liveness и readiness

### `/health/live`

Показывает, что процесс приложения жив и способен отвечать по HTTP.

Не требует установленной ML-модели.

### `/health/ready`

Проверяет как минимум default provider.

Если default provider не готов, endpoint возвращает HTTP 503.

Это позволяет контейнеру стартовать даже до установки модели, сохраняя корректную семантику readiness.

## 8. Синхронный inference

Большинство локальных движков выполняют синхронный CPU/GPU inference.

FastAPI route может быть `async`, но provider call не должен надолго блокировать event loop.

Для MVP использовать простой thread offload, например `anyio.to_thread.run_sync`.

Application services и HTTP health/list endpoints используют общий `WorkerPool`.
Лимит `MAX_CONCURRENT_OPERATIONS` удерживается до завершения worker, даже после
отмены ожидания. Проверки `health()`/`capabilities()` также выполняются в worker.
Отменённый запрос, который ещё не начал работу, не запускается позднее.

Если измерения покажут, что отдельные движки плохо масштабируются в threads или требуют process isolation, это решается на provider/application уровне без изменения внешнего API.

## 9. Timeout

Application service должен применять общий configurable timeout.

Он включает ожидание свободного слота, проверки готовности и inference.

Важно: отмена await по timeout не всегда физически прерывает CPU inference в worker thread. В MVP timeout прежде всего ограничивает время ожидания клиента и возвращает согласованную ошибку. Если жёсткое завершение inference станет обязательным, provider следует вынести в отдельный worker process.

## 10. Логирование

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

## 11. Будущее масштабирование

Без изменения `/v1/translate` можно добавить:

- Ollama provider;
- automatic language detection перед provider selection;
- fallback policy;
- caching layer;
- batch endpoint;
- API key middleware;
- metrics `/metrics`;
- отдельные inference workers.

Все это вне MVP.
