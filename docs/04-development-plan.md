# План разработки

## Phase 1 — каркас и контракт

Цель: получить работающий HTTP сервис без реальной ML-модели и закрепить API тестами.

Задачи:

- [x] создать `pyproject.toml` и `src` layout;
- [x] подключить FastAPI, Uvicorn, Pydantic v2, pytest, httpx;
- [x] реализовать application config;
- [x] реализовать request id middleware;
- [x] реализовать Pydantic API models;
- [x] реализовать domain provider protocol/types;
- [x] реализовать `TranslatorRegistry`;
- [x] реализовать `TranslationService`;
- [x] реализовать `FakeTranslatorProvider` только для tests/dev;
- [x] реализовать `POST /v1/translate`;
- [x] реализовать `GET /v1/translators`;
- [x] реализовать `/health/live` и `/health/ready`;
- [x] реализовать единый error envelope;
- [x] покрыть API contract тестами;
- [x] сверить реализацию с `openapi.yaml`.

Результат: все HTTP сценарии можно проверить без Argos и без скачивания модели.

## Phase 2 — Argos Translate provider

- [x] добавить зависимость Argos Translate;
- [x] реализовать `ArgosProvider`;
- [x] обнаруживать локально установленные language packages;
- [x] реализовать `health()`;
- [x] реализовать проверку language pair;
- [x] не разрешать unknown `translator_params`;
- [x] нормализовать Argos exceptions;
- [x] добавить явный скрипт установки модели;
- [x] добавить integration test `en -> ru`, автоматически skip если модели нет.

Результат: минимальный request реально переводит English -> Russian локально, без
платного или квотируемого API перевода. Загрузка моделей в runtime допустима.

## Phase 2.1 — Marian/CTranslate2 provider

- [x] добавить прямые зависимости CTranslate2, Transformers и SentencePiece;
- [x] реализовать `MarianProvider` за существующей provider abstraction;
- [x] обнаруживать модели и языковые пары через manifest;
- [x] лениво загружать и кэшировать CTranslate2 runtime;
- [x] нормализовать ошибки и отклонять unknown `translator_params`;
- [x] добавить скрипт загрузки и конвертации MarianMT/OPUS-MT;
- [x] хранить модели вне репозитория;
- [x] добавить unit и model-gated integration tests.

Результат: клиент может выбрать `"translator": "marian"`, не меняя остальные
обязательные поля API.

## Phase 3 — эксплуатационный минимум

- [ ] structured logging;
- [ ] измерение `duration_ms`;
- [ ] configurable max text length;
- [ ] configurable timeout;
- [ ] thread offload для sync inference;
- [ ] Dockerfile;
- [ ] `.env.example`;
- [ ] docker-compose для локального запуска;
- [ ] graceful startup/shutdown;
- [ ] README quick-start команды.

## Phase 4 — hardening MVP

- [ ] тесты ошибок и edge cases;
- [ ] тест конкурентных запросов;
- [ ] запрет утечки traceback в response;
- [ ] проверка логов на отсутствие полного текста;
- [ ] smoke test через curl;
- [ ] финальная сверка docs/OpenAPI/implementation.

## После MVP — только отдельными задачами

Другие будущие направления:

- Ollama provider;
- batch API;
- API key;
- cache;
- metrics;
- language detection;
- fallback между engines.

## Suggested Codex task #1

```text
Implement Phase 1 from docs/04-development-plan.md.
Treat docs/01-product-requirements.md and docs/03-api-contract.md as authoritative.
Do not integrate Argos Translate yet. Use a FakeTranslatorProvider in tests so the HTTP contract is fully testable without ML model downloads.
Before finishing, run the full test suite and check that the generated FastAPI OpenAPI behavior is compatible with the repository's openapi.yaml.
```

## Suggested Codex task #2

```text
Implement Phase 2 from docs/04-development-plan.md by adding an Argos Translate provider behind the existing TranslatorProvider abstraction.
Do not change the public /v1/translate contract.
Translation inference must be local and user text must never be sent to an external service. Runtime downloads of public models and support files are allowed. Add an explicit model-installation script for en -> ru and make readiness false when the required translation model is absent.
```
