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

Создаёт аннотацию в 2–3 предложениях на преобладающем языке исходного материала. Внешний ИИ-провайдер
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
Значение `annotator: "qwen_local"` выбирает локальный Qwen3.5-4B Q5_K_M через
llama.cpp. Адрес и имя модели задаются на сервере переменными
`QWEN_LOCAL_BASE_URL` и `QWEN_LOCAL_MODEL`. Оба провайдера принимают
`annotator_params.model`, например `{"model":"qwen3.8-flash"}`. Это непустая
строка до 200 печатных символов; пробелы по краям удаляются. Если поле отсутствует,
используется модель из окружения. `null`, другие типы и неизвестные параметры
возвращают `422 invalid_annotator_params`. Имя проверяет модельный сервер;
отклонённый выбор модели также возвращает эту ошибку. Для `qwen_local` модель
должна быть доступна на настроенном llama.cpp сервере; параметр не загружает
и не переключает GGUF-файл автоматически.

Ответ `200`:

```json
{
  "annotation": "The article describes a study. Its authors present the main findings.",
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

Для `qwen_local` аннотация должна кратко пересказывать материал своими словами,
объединять повторяющиеся мысли и опускать второстепенные перечисления. Для
текста от 30 слов результат ограничен 25 словами. Превышение лимита или
почти полное копирование (сходство последовательностей слов не менее 0.85)
вызывает одну повторную попытку внутри общего worker/таймаута.
Повторный дефект возвращает `502 annotation_failed`. Короткие источники
не подпадают под проверку копирования и длины. Новые слова со смешанными
латинскими и кириллическими буквами также вызывают повторную попытку независимо
от длины источника. Эти проверки не гарантируют смысловую точность.

## POST `/v1/title`

Формирует один короткий информативный заголовок по готовому plain text.

```json
{"text":"Moon phases","annotator":"iishko","annotator_params":{"model":"qwen3.8-flash"}}
```

Обязателен только `text`; неизвестные поля запрещены.
`text` — непустая после проверки пробелов строка, максимум 30 000 символов Unicode.
Весь вход передаётся модели без усечения. Модель пишет на преобладающем языке
исходного материала; при смешанном входе выбирает преобладающий язык и сохраняет
имена и технические обозначения в оригинале. Не следует переводить весь материал. URL, HTML и файлы
не извлекаются: клиент передаёт содержательный текст.

Необязательные `annotator` и `annotator_params.model` работают так же, как в
`/v1/annotate`: default provider `DEFAULT_ANNOTATOR`, модель из `IISHKO_MODEL`
или `QWEN_LOCAL_MODEL`. При выборе внешнего `iishko` текст отправляется ему.
`qwen_local` выполняет генерацию через настроенный локальный llama.cpp сервер.

```json
{"title":"Moon phases","metadata":{"duration_ms":842}}
```

Слова с латинскими и кириллическими буквами вместе допускаются только если
они присутствуют в исходном тексте (например, оригинальное название). Новые
смешанные слова вызывают повторную генерацию, затем `502 invalid_title`.

Ответ содержит только эти поля. Заголовок — одна строка plain text, максимум
120 символов Unicode, без обрамляющих кавычек и разметки. Клиент экранирует его
при отображении. Ориентир — 6–12 слов; короткие исходные названия допустимы.
Инструкции внутри материала считаются данными. Задание модели требует сохранять
факты, неопределённость и различающие детали, удалять технический шум и выдавать
ошибку при недостатке содержания. Эти смысловые свойства проверяются оценочной
подборкой, а не только проверкой формата.

Пустой, многострочный, размеченный или слишком длинный ответ допускает одну
повторную генерацию с указанием нарушения, без механического обрезания.
Общий `ANNOTATION_TIMEOUT_SECONDS` (default 100 секунд) включает ожидание общего
worker, проверку готовности и обе попытки. Сетевой timeout одного вызова задаётся
`ANNOTATION_PROVIDER_TIMEOUT_SECONDS` (default 90 секунд). Общий лимит
`MAX_CONCURRENT_OPERATIONS` применяется вместе с переводом и аннотациями.
После таймаута начатый вызов может продолжать занимать слот до завершения;
последующая попытка не запускается.

| HTTP | Код | Причина |
|---:|---|---|
| 400 | `invalid_request` | Невалидный JSON |
| 404 | `unknown_annotator` | Незарегистрированный provider |
| 413 | `text_too_large`, `request_body_too_large` | Лимит текста или HTTP body |
| 422 | `invalid_request` | Поля, типы, пустой текст |
| 422 | `invalid_annotator_params` | Параметры или выбор модели отклонены |
| 422 | `insufficient_content` | Недостаточно содержательной информации |
| 502 | `invalid_title` | Невалидный результат после двух попыток |
| 502 | `annotation_failed` | Ошибка модельного сервера |
| 503 | `annotator_unavailable` | Provider недоступен, не настроен или перегружен |
| 504 | `annotation_timeout` | Общий или сетевой timeout |
| 500 | `title_failed` | Непредвиденная внутренняя ошибка |

Ошибки используют общий envelope. Логи содержат request ID, метод, размеры
входа и результата, длительность, число попыток, статус и код ошибки. Текст,
ответ модели, ключи и параметры модели в обычные логи не включаются.
Готовность `/health/ready` по-прежнему относится к default переводчику.

## Изменение контракта: сохранение исходного языка

У `/v1/title` удалены request/response `target_language`, у `/v1/annotate`
удалено response `language`. Языковые поля в запросах обоих методов запрещены
строгой схемой: title возвращает `422 invalid_request`, annotate — существующий
`400 invalid_request`. Клиентам нужно перестать передавать языковые поля и
читать их из ответа. Аннотация больше не переводит текст автоматически на русский.
Модель сохраняет преобладающий язык текста после подготовки URL/HTML.
Поддержка и качество языка зависят от выбранной модели; форматная проверка не
гарантирует отсутствие языковых или смысловых ошибок. `/v1/translate` сохраняет
свой контракт с source/target language.

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
