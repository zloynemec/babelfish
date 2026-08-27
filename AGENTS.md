# AGENTS.md — инструкции для Codex

## Контекст

Это новый внутренний проект: сервис локального машинного перевода, доступный по HTTP API.

Главная цель — отделить перевод от приложений-потребителей и дать им единый стабильный контракт независимо от используемого локального движка.

MVP должен работать без авторизации. Первый реальный provider — Argos Translate.

## Источники требований

Перед изменениями прочитай:

1. `README.md`
2. `docs/01-product-requirements.md`
3. `docs/02-architecture.md`
4. `docs/03-api-contract.md`
5. `docs/04-development-plan.md`
6. `docs/05-testing-and-acceptance.md`
7. `openapi.yaml`

При конфликте требований приоритет такой:

1. `docs/01-product-requirements.md`
2. `docs/03-api-contract.md`
3. `openapi.yaml`
4. `docs/02-architecture.md`
5. остальные документы

Если контракт меняется намеренно, обновляй одновременно Markdown-документацию, OpenAPI и тесты.

## Технические ограничения

- Python 3.12+.
- FastAPI + Pydantic v2.
- Код приложения расположен в `src/translation_service`.
- Использовать type hints во всём production-коде.
- Не добавлять БД в MVP.
- Не добавлять авторизацию в MVP.
- Не добавлять очередь сообщений в MVP.
- Выполнять inference локально и не отправлять пользовательский текст внешним сервисам.
- Не использовать платные или квотируемые API перевода.
- Разрешено загружать публичные модели и служебные файлы при startup или первом запросе;
  такие загрузки не должны содержать пользовательский текст.
- Внешние движки должны подключаться только через provider abstraction.
- API не должен импортировать Argos Translate напрямую.

## Архитектурное правило

Маршрут HTTP -> application service -> provider registry -> provider.

Запрещено делать так:

`route -> argostranslate.translate.translate(...)`

Нужно делать так:

`route -> TranslationService -> TranslatorRegistry -> ArgosProvider`

Это ключевое требование проекта.

## Provider interface

Реализация может отличаться синтаксически, но должна сохранять следующие возможности:

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

Provider получает уже нормализованный request и не должен зависеть от FastAPI request/response objects.

## Работа с provider-specific параметрами

В публичном API поле называется `translator_params`.

Правила:

- поле необязательное;
- default `{}`;
- его содержимое передаётся только выбранному provider;
- provider обязан валидировать поддерживаемые параметры;
- неизвестные/некорректные параметры дают предсказуемую ошибку API;
- API-контракт не должен перечислять параметры всех будущих движков в основной модели TranslateRequest.

## Default behavior

Минимально валидный body:

```json
{
  "text": "Hello",
  "target_language": "ru"
}
```

При этом сервис использует:

- `source_language = DEFAULT_SOURCE_LANGUAGE`, по умолчанию `en`;
- `translator = DEFAULT_TRANSLATOR`, по умолчанию `argos`.

## Ошибки

Все прикладные ошибки должны иметь единый JSON envelope с машинным `code`.

Не возвращай пользователю Python traceback, абсолютные пути или внутренние детали ML-библиотеки.

## Concurrency

Перевод является CPU-bound/синхронной операцией. Не блокируй event loop долгим inference напрямую внутри `async def` route. В MVP допустим thread worker (`anyio.to_thread.run_sync`) или другой простой изолирующий механизм.

Не вводи Celery/RabbitMQ/Redis без отдельного требования.

## Модели

Сервис должен быть способен стартовать без установленной модели, чтобы `/health/live` отвечал успешно. Но `/health/ready` должен сообщать, что default provider не готов, а `/v1/translate` — возвращать `503 translator_unavailable`.

Модели можно устанавливать отдельной явной командой/скриптом. Движок также может
дозагрузить необходимую модель или служебный файл в runtime, если это не обращение
к платному/квотируемому API и пользовательский текст не покидает сервис.

## Тесты

До реального Argos provider сначала реализовать `FakeTranslatorProvider` для unit/integration tests. Контракт HTTP должен тестироваться без скачивания ML-моделей.

Для Argos добавить отдельные integration tests, которые можно пропустить, если модель отсутствует.

## Definition of Done для любого изменения

- код типизирован;
- formatter/linter проходят;
- unit tests проходят;
- contract/integration tests проходят;
- публичный API не изменён случайно;
- документация обновлена, если менялось внешнее поведение.

## Первая задача

Выполни `Phase 1` из `docs/04-development-plan.md`. Не начинай оптимизацию, batch API, кэш или дополнительные движки до завершения MVP-контракта.
