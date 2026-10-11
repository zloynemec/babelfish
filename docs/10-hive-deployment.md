# Публикация на hive

Production Compose публикует API по адресу `https://babelfish.linktool.ru` через
существующий Traefik на hive. Схема повторяет warpbuster: внешняя Docker-сеть
`traefik`, entrypoint `https`, certresolver `letsencrypt`, сборка через SSH Docker
context. API слушает порт `8000` только внутри Docker-сети.

Access logs Uvicorn и Traefik отключены: вместо них приложение пишет JSON-записи
через `uvicorn.error.translation_service` в stderr, доступный через Compose logs.
Записи содержат request id, статус, результат и длительность; для перевода также
provider, языки и длину текста. Текст, HTML, перевод, URL и query string не пишутся.

## Перед первым запуском

- A-запись `babelfish.linktool.ru` должна указывать на публичный IP hive.
  Если есть AAAA-запись, её IPv6 тоже должен вести на hive.
- На hive должны работать Docker, Traefik, сеть `traefik` и доступ к портам 80/443.
- На машине, с которой выполняется публикация, нужны Git, SSH, Docker CLI и
  Docker Compose с поддержкой `up --wait`.
- SSH-доступ к `root@hive.ohmygames.ru` должен быть настроен заранее.

```bash
cp .env.prod.example .env.prod
chmod 600 .env.prod
```

При необходимости заполните `IISHKO_API_KEY` в `.env.prod` для `/v1/annotate`.
Пустой ключ не мешает запуску и переводу; аннотатор `iishko` будет не готов.
Локальный `.env` для разработки не используется при публикации и не попадает
в Docker build context. `.env.prod` также исключён из Git и образа.

`APP_CPUS=2`, `APP_MEMORY=4g` и `INFERENCE_THREADS=2` — начальные лимиты для
CPU inference. При увеличении числа потоков согласуйте его с выделенными CPU.
Образ содержит CPU-версию PyTorch и зависимости обоих переводчиков; модели
устанавливаются отдельно. Первая сборка требует интернета и может занять
несколько минут. Используется один Uvicorn worker, чтобы не дублировать модели
в памяти.

## Публикация с локальной машины

```bash
./deploy.prod.sh
```

Скрипт создаёт context `babelfish-hive`, проверяет его SSH endpoint и сеть
Traefik, создаёт хранилище с владельцем `10001:10001`, собирает образ на hive,
устанавливает и проверяет Qwen3-4B Q4_K_M, запускает приватный llama.cpp,
устанавливает Argos `en -> ru`, запускает API и проверяет readiness внутри
контейнера. Повторная установка уже имеющейся Argos-модели безопасна.
Скрипт не изменяет DNS или конфигурацию общего Traefik.

Можно переопределить адрес SSH и имя context:

```bash
HIVE_SSH_TARGET=root@hive.ohmygames.ru \
HIVE_DOCKER_CONTEXT=babelfish-hive ./deploy.prod.sh
```

По умолчанию `DEFAULT_TRANSLATOR=argos`. Если хотите сделать `marian` default,
сначала установите Marian командой из следующего раздела, затем измените
`.env.prod` и повторите запуск. Скрипт всегда устанавливает Argos `en -> ru`;
остальные пары и Marian устанавливаются явно.

## Хранилище и дополнительные модели

Bind mount на hive: `/apps/focus-hive-site-babelfish/data` → `/data`.
Он содержит пакеты Argos, MiniSBD, Marian, конфигурацию движков и кэш Hugging Face.
`HOME` и XDG-каталоги направлены туда, включая MiniSBD, который использует
`$HOME/.cache`. Пересоздание контейнера сохраняет модели. Для резервной копии
копируйте этот каталог; не удаляйте его при обновлении.

Команды ниже выполняются из локального репозитория, а контейнеры запускаются
на hive благодаря `--context`:

```bash
# Дополнительная пара Argos.
docker --context babelfish-hive compose --env-file .env.prod \
  -f docker-compose.prod.yml run --rm --no-deps babelfish \
  python scripts/install_argos_model.py --from de --to ru

# Marian en -> ru (скачивание и конвертация в int8).
docker --context babelfish-hive compose --env-file .env.prod \
  -f docker-compose.prod.yml run --rm --no-deps babelfish \
  python scripts/install_marian_model.py --from en --to ru

# Перезапуск после изменения установленного набора моделей.
docker --context babelfish-hive compose --env-file .env.prod \
  -f docker-compose.prod.yml restart babelfish
```

Marian-конвертация может потребовать больше RAM, чем обычный inference;
при нехватке увеличьте `APP_MEMORY` на время установки.

## Локальный Qwen на production

Compose запускает `qwen-local` на официальном CPU-образе llama.cpp, закреплённом
по digest. Qwen3-4B Q4_K_M (2.5 GB) загружается скриптом
`scripts/install_qwen_model.sh` из официального Qwen/Hugging Face с закреплённым
revision и проверкой SHA256. Скрипт выполняется на hive через SSH перед запуском
модели; повторный запуск проверяет существующий файл и не загружает его повторно.
Модель хранится отдельно: `/apps/focus-hive-site-babelfish/qwen`, mount read-only.

`QWEN_LOCAL_BASE_URL=http://qwen-local:8080/v1`, `QWEN_LOCAL_MODEL=qwen3-4b`.
Сеть `qwen` внутренняя, доступна API и llama.cpp; порты модели не публикуются
на хосте и не маршрутизируются через Traefik. Контейнер работает от UID/GID
10001, с лимитами 4 CPU и 10 GB RAM. Контекст — 32768 токенов, один inference
slot, reasoning отключён. Контентные логи llama.cpp отключены.

Default `iishko` сохраняется; для локальной генерации нужен явный выбор:

```json
{"text":"Engineers visited the battery testing laboratory.","annotator":"qwen_local","annotator_params":{"model":"qwen3-4b"}}
```

Этот запрос направляется в `/v1/title`. Для `/v1/annotate` используются те же
поля выбора provider/model. Оба метода сохраняют преобладающий язык входного текста. CPU-генерация зависит от
размера входа; применяются существующие таймауты 90/100 секунд. Длинные входы
могут не уложиться в них. `annotator_params.model` не загружает новые веса.
Готовность модели показывается в `/v1/annotators`; `/health/ready` по-прежнему
проверяет default переводчик.

[Официальный Docker-образ llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md),
[флаги сервера](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md).

Если модель уже установлена, для применения только конфигурации без пересборки:

```bash
docker --context babelfish-hive compose --env-file .env.prod \
  -f docker-compose.prod.yml up -d --no-build --wait qwen-local babelfish
```

При откате API на старый образ локальную модель можно оставить работающей;
для возврата прежнего подключения восстановите предыдущий `QWEN_LOCAL_BASE_URL`.

Контейнер запускается от UID/GID `10001:10001`, с read-only файловой системой;
запись разрешена в `/data` и временный `/tmp`. Docker healthcheck проверяет
`/health/live`, поэтому API может стартовать без моделей. В таком состоянии
`/health/ready` и `/v1/translate` возвращают `503 translator_unavailable`.
Traefik не использует readiness как условие публикации.

## Проверка HTTPS

```bash
curl --fail https://babelfish.linktool.ru/health/live
curl --fail https://babelfish.linktool.ru/health/ready
curl --fail https://babelfish.linktool.ru/v1/translators
curl --fail https://babelfish.linktool.ru/v1/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello world","target_language":"ru"}'
```

Документация API: <https://babelfish.linktool.ru/docs>.
TLS-сертификат выпускает существующий Traefik после настройки DNS.

## Обновление и диагностика

Перед публикацией нового релиза задайте уникальный `IMAGE_TAG` в `.env.prod`,
чтобы сохранить предыдущий образ для отката, затем:

```bash
git pull
./deploy.prod.sh
docker --context babelfish-hive compose --env-file .env.prod \
  -f docker-compose.prod.yml logs --tail=100 babelfish
```

Для отката верните предыдущий `IMAGE_TAG` в `.env.prod` и запустите `up` без
сборки (образ должен оставаться на hive):

```bash
docker --context babelfish-hive compose --env-file .env.prod \
  -f docker-compose.prod.yml up -d --no-build --pull never --wait babelfish
```

При отсутствии ключа ИИШКО отдельно проверить состояние аннотаторов можно через
`GET /v1/annotators`. Это не влияет на readiness перевода.
