# API-контракт

Base URL примера: `http://localhost:8000`.

Версия API включена в path: `/v1/...`.

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
