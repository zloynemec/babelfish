# Тестирование и критерии готовности

## Аннотирование

Контракт `/v1/annotate` тестируется с fake fetcher и fake annotator, без
обращения к внешнему сервису. Проверяются `url`, `html`, `text`, требование ровно
одного входа, выбор provider, `annotator_params`, ошибки, лимиты и отсутствие
молчаливого усечения `text`. Отдельные unit tests проверяют удаление служебных
HTML-элементов, запрет опасных URL и формирование запроса ИИШКО с моделью
`qwen3.8-flash`. Живой вызов ИИШКО не входит в обязательный набор тестов.
Для `qwen_local` unit tests проверяют локальный endpoint, идентичный системный
запрос, состояние готовности и нормализацию сетевых ошибок. Реальный запуск
llama.cpp и сравнительный прогон выполняются отдельно от обязательных тестов.

## 1. Unit tests

Минимально покрыть:

- config defaults;
- registry registration/lookup;
- duplicate provider name;
- unknown provider;
- TranslationService default source language;
- TranslationService default translator;
- explicit translator selection;
- forwarding `translator_params` unchanged to provider;
- provider error normalization;
- max text length;
- whitespace-only text.

## 2. HTTP contract tests

### T-001 Минимальный запрос

Request:

```json
{
  "text": "Hello",
  "target_language": "ru"
}
```

Ожидание:

- 200;
- использован default translator;
- использован default source language;
- response содержит `translation`, `translator`, языки и `metadata.duration_ms`.

### T-002 Явный source language

Переданный `source_language` имеет приоритет над default.

### T-003 Явный translator

Переданный `translator` имеет приоритет над default.

### T-004 Translator params

Объект `translator_params` доходит до выбранного fake provider.

### T-005 Unknown translator

Ожидание:

- 404;
- `error.code = unknown_translator`.

### T-006 Unsupported language pair

Ожидание:

- 422;
- `error.code = unsupported_language_pair`.

### T-007 Provider unavailable

Ожидание:

- 503;
- `error.code = translator_unavailable`.

### T-008 Invalid provider params

Ожидание:

- 422;
- `error.code = invalid_translator_params`.

### T-009 Oversized text

Ожидание:

- 413;
- `error.code = text_too_large`.

### T-010 Timeout

Ожидание:

- 504;
- `error.code = translation_timeout`.

### T-011 Liveness without model

`/health/live` возвращает 200 даже если Argos model отсутствует.

### T-012 Readiness without model

`/health/ready` возвращает 503, если default provider не готов.

## 3. Argos integration tests

Эти тесты должны быть помечены отдельным marker, например `argos_integration`.

Если локальная `en -> ru` модель не установлена, тест пропускается, а не начинает
скачивание из сети. Это обеспечивает детерминированность test suite и не запрещает
runtime-загрузки в production.

Минимальные проверки:

- provider ready при установленной модели;
- `en -> ru` возвращает непустую строку;
- unsupported pair корректно нормализуется;
- unknown `translator_params` отвергаются.

Не нужно проверять конкретную дословную формулировку перевода: модель может меняться. Допустимо проверять лишь базовые свойства результата или небольшой стабильный smoke case.

## 4. Marian integration tests

Тесты помечаются marker `marian_integration` и автоматически пропускаются, если
в `MARIAN_MODELS_DIR` отсутствует модель `en -> ru`.

Минимальные проверки:

- обнаружение manifest и языковой пары;
- локальная токенизация и CTranslate2 inference;
- непустой результат `en -> ru` через HTTP;
- нормализация ошибок загрузки и inference;
- отсутствие абсолютных путей в публичной ошибке.

## 5. Security/robustness checks MVP

Регрессионные проверки P1 выполняются без моделей и внешних запросов:

- размер body проверяется до JSON validation, с Content-Length, без него и с
  заниженным значением; точная граница разрешена;
- медленные provider health checks не блокируют liveness;
- timeout включает проверки готовности и ожидание worker;
- abandoned worker удерживает слот до завершения, отменённый ожидающий запрос
  не начинает работу позднее;
- после timeout подготовки или provider checks последующий inference не запускается;
- внедрённый AnnotationService использует общий лимит приложения;
- HTTP-журнал содержит request id, статус, длительность и результат для успеха,
  validation errors, 413, 503, 504 и provider failure, без текста и query string;
- Marian сохраняет весь допустимый вход, отклоняет превышение токенного лимита
  и результат без EOS.

Хотя авторизации нет:

- traceback не попадает в response;
- исключения provider не раскрывают локальные абсолютные пути;
- request body ограничен разумным размером;
- полный текст не попадает в production logs;
- неизвестные JSON fields обрабатываются согласно выбранной строгой policy и тестируются;
- `translator_params` не используется для произвольного импорта модулей/исполнения команд.

Рекомендуемая policy для API request: `extra='forbid'` для верхнего уровня, чтобы опечатки не игнорировались молча.

## 6. Performance baseline

Для MVP не устанавливается жёсткий SLA, потому что скорость зависит от CPU и модели.

Но smoke benchmark должен фиксировать:

- длину input;
- provider;
- duration;
- количество последовательных запросов;
- количество параллельных запросов.

Это даст базу перед добавлением CTranslate2.

## 7. Definition of Done MVP

MVP считается готовым, когда одновременно выполняются условия:

- [ ] сервис стартует локально;
- [ ] `/health/live` работает;
- [ ] `/health/ready` корректно отражает наличие default translator model;
- [ ] минимальный request требует только `text` и `target_language`;
- [ ] default source = `en` конфигурируем;
- [ ] default translator = `argos` конфигурируем;
- [ ] можно выбрать translator полем `translator`;
- [ ] можно передать `translator_params`;
- [ ] Argos `en -> ru` выполняет inference локально;
- [ ] Marian/CTranslate2 `en -> ru` доступен через `translator=marian` при установленной модели;
- [ ] текст запросов `/v1/translate` не отправляется во внешние сервисы;
- [ ] сервис не использует платные или квотируемые API перевода;
- [ ] допустимые runtime-загрузки ограничены моделями и служебными файлами;
- [ ] единый error contract соблюдается;
- [ ] unit и HTTP contract tests проходят без ML-модели;
- [ ] Argos integration test проходит при установленной модели;
- [ ] Marian integration test проходит при установленной модели;
- [ ] README содержит воспроизводимый quick start;
- [ ] реализация, Markdown docs и OpenAPI не противоречат друг другу.
