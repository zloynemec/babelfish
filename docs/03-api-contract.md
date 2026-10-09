# API-контракт

Base URL примера: `http://localhost:8000`.

Версия API включена в path: `/v1/...`.

В OpenAPI и Scalar методы `/v1/translate` и `/v1/translators` объединены тегом
`translation`, а `/v1/annotate` и `/v1/annotators` — тегом `annotation`.

Для всех HTTP endpoints размер body ограничен `MAX_REQUEST_BODY_BYTES`
(default 16 000 000 байт). Лимит проверяется до разбора JSON и действует также
без `Content-Length`. Превышение возвращает `413 request_body_too_large`
в общем error envelope с `details.max_request_body_bytes`.

## POST `/v1/annotate`

Создаёт аннотацию на русском языке в 2–3 предложениях. Внешний ИИ-провайдер
получает подготовленный текст. Запрос должен содержать **ровно одно** из полей
`url`, `html`, `text`:

```json
{"url":"https://example.org/article"}
```

```json
{"html":"<main><p>Article content.</p></main>","annotator":"iishko"}
```

```json
{"text":"Article content.","annotator_params":{}}
```

`url` допускает только публичные HTTP(S) ресурсы с `text/html` или `text/plain`.
`html` очищается от разметки, скриптов и служебных элементов. `text` передаётся
модели без изменения; при превышении лимита возвращается ошибка. Поля
`annotator` (default `DEFAULT_ANNOTATOR=iishko`) и `annotator_params` (default
`{}`) необязательны. Параметры валидирует выбранный provider. Default модель
ИИШКО — `qwen3.8-flash`.
Значение `annotator: "qwen_local"` выбирает локальный Qwen3-4B Q4_K_M через
llama.cpp. Адрес и имя модели задаются на сервере переменными
`QWEN_LOCAL_BASE_URL` и `QWEN_LOCAL_MODEL`; `annotator_params` пока должен быть
пустым для обоих провайдеров.

Ответ `200`:

```json
{
  "annotation": "Статья описывает исследование. Авторы приводят основные выводы.",
  "language": "ru",
  "annotator": "iishko",
  "metadata": {"duration_ms": 850, "truncated": false}
}
```

`metadata.truncated=true` означает, что для URL/HTML использована только часть
длинного извлечённого текста. Возможные ошибки в едином envelope:
`invalid_request` (400), `url_not_allowed` (403), `unknown_annotator` (404),
`content_too_large` (413), `unsupported_content_type` (415),
`content_not_extractable` и `invalid_annotator_params` (422),
`content_fetch_failed` и `annotation_failed` (502), `annotator_unavailable`
(503), `annotation_timeout` (504).

## GET `/v1/annotators`

Возвращает зарегистрированных аннотаторов и их готовность по конфигурации:

```json
{"annotators":[{"name":"iishko","ready":true},{"name":"qwen_local","ready":true}],"default_annotator":"iishko"}
```

`/health/ready` продолжает отражать готовность default переводчика.

## 1. POST `/v1/translate`

Перевод текста.

### Минимальный request

```json
{
  "text": "The spacecraft entered orbit.",
  "target_language": "ru"
}
```

### Полный request

```json
{
  "text": "The spacecraft entered orbit.",
  "target_language": "ru",
  "source_language": "en",
  "translator": "argos",
  "translator_params": {}
}
```

### Поля request

| Поле | Тип | Required | Default | Описание |
|---|---|---:|---|---|
| `text` | string | да | — | Исходный текст |
| `target_language` | string | да | — | Целевой язык |
| `source_language` | string | нет | `DEFAULT_SOURCE_LANGUAGE` | Исходный язык |
| `translator` | string | нет | `DEFAULT_TRANSLATOR` | Имя provider |
| `translator_params` | object | нет | `{}` | Provider-specific параметры |

### 200 response

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

### Response fields

| Поле | Тип | Описание |
|---|---|---|
| `translation` | string | Результат перевода |
| `source_language` | string | Фактически использованный source language |
| `target_language` | string | Целевой язык |
| `translator` | string | Фактически использованный provider |
| `metadata` | object | Стабильные/диагностические метаданные |

`metadata.duration_ms` должен присутствовать. Дополнительные provider-specific metadata допустимы только если они не содержат чувствительных внутренних данных.

## 2. GET `/v1/translators`

Возвращает зарегистрированные переводчики и состояние готовности.

Пример:

```json
{
  "translators": [
    {
      "name": "argos",
      "ready": true,
      "supported_language_pairs": [
        {"source": "en", "target": "ru"}
      ]
    },
    {
      "name": "marian",
      "ready": false,
      "supported_language_pairs": []
    }
  ],
  "default_translator": "argos"
}
```

Если provider не способен дешево перечислить все пары, `supported_language_pairs` может быть `null`.

## 3. GET `/health/live`

### 200

```json
{
  "status": "ok"
}
```

## 4. GET `/health/ready`

### 200

```json
{
  "status": "ready",
  "default_translator": "argos"
}
```

### 503

```json
{
  "error": {
    "code": "translator_unavailable",
    "message": "Default translator is not ready",
    "details": {
      "translator": "argos"
    },
    "request_id": "01J..."
  }
}
```

## 5. Error envelope

Все прикладные ошибки:

```json
{
  "error": {
    "code": "unsupported_language_pair",
    "message": "Translator does not support requested language pair",
    "details": {
      "translator": "argos",
      "source_language": "en",
      "target_language": "xx"
    },
    "request_id": "01J..."
  }
}
```

### Коды ошибок

| HTTP | `code` | Когда |
|---:|---|---|
| 400 | `invalid_request` | Семантически некорректный запрос |
| 413 | `text_too_large` | `text` превышает configured limit |
| 413 | `request_body_too_large` | HTTP body превышает байтовый лимит до разбора JSON |
| 422 | `invalid_translator_params` | Параметры provider некорректны |
| 404 | `unknown_translator` | Неизвестный `translator` |
| 422 | `unsupported_language_pair` | Provider не поддерживает пару |
| 503 | `translator_unavailable` | Provider/model не готов |
| 504 | `translation_timeout` | Превышен timeout |
| 500 | `translation_failed` | Непредвиденная ошибка inference |

FastAPI validation errors также следует привести к согласованному публичному формату, а не оставлять второй несовместимый error contract.

## 6. Validation rules

### `text`

- string;
- после проверки не должен быть пустым;
- whitespace-only запрещён;
- максимальная длина определяется `MAX_TEXT_LENGTH`.

Не следует автоматически `strip()` сам переводимый текст перед передачей provider, чтобы не менять контент клиента. Проверка пустоты может выполняться через `text.strip()`.

Marian дополнительно проверяет токенный лимит tokenizer (не более 1024 токенов,
включая служебные). Более длинный вход возвращает `413 text_too_large` с
`details.translator`, `details.max_input_tokens` и `details.actual_tokens`.
Сервис не возвращает молча усечённый перевод. Генерация Marian без EOS в пределах
1024 токенов возвращает `500 translation_failed`.

Timeout перевода/аннотации включает ожидание worker и проверки provider.
Если все `MAX_CONCURRENT_OPERATIONS` слоты заняты, запрос ждёт в пределах своего
timeout; по истечении возвращается существующий код `translation_timeout` или
`annotation_timeout`. Списки показывают провайдер как неготовый, если проверка
не завершилась за соответствующий timeout; `/health/ready` возвращает `503`.

### Language codes

MVP:

- lower-case ASCII;
- предпочтительно ISO 639-1;
- regex уровня `^[a-z]{2,3}(-[A-Za-z0-9]+)*$` допустим для будущего расширения.

### `translator`

- непустая строка;
- нормализовать к lowercase при регистрации/поиске;
- публичное имя provider стабильно.

### `translator_params`

- JSON object;
- default `{}`;
- конкретная schema определяется provider.

## 7. API compatibility

Изменения, которые считаются breaking:

- переименование существующих полей;
- изменение semantics default translator/source language без конфигурации;
- удаление существующего error code;
- изменение типа существующего response field.

Новые необязательные поля и новые provider names можно добавлять без новой версии API.
