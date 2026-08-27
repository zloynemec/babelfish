# Подключение языков Argos Translate

Argos работает с языковыми пакетами, каждый из которых задаёт направление
перевода. Пакет `en -> ru` не добавляет обратное направление `ru -> en`: его нужно
установить отдельно.

## Установка новой языковой пары

Активируйте виртуальное окружение проекта и выполните:

```bash
python scripts/install_argos_model.py --from SOURCE --to TARGET
```

Например:

```bash
# Английский -> русский
python scripts/install_argos_model.py --from en --to ru

# Русский -> английский
python scripts/install_argos_model.py --from ru --to en

# Английский -> немецкий
python scripts/install_argos_model.py --from en --to de
```

Используются короткие коды языков, например `en`, `ru`, `de`, `fr`, `es`, `it`.
Скрипт завершится с сообщением `No Argos model found`, если в публичном каталоге
Argos нет выбранного направления.

После установки перезапустите сервис. Новая пара появится в:

```bash
curl http://localhost:8000/v1/translators
```

Пример запроса для `en -> de`:

```bash
curl -X POST http://localhost:8000/v1/translate \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "Hello world",
    "source_language": "en",
    "target_language": "de",
    "translator": "argos"
  }'
```

## Просмотр доступных пакетов

Следующая команда обновляет публичный индекс Argos и выводит все доступные
направления:

```bash
python - <<'PY'
from argostranslate import package

package.update_package_index()
pairs = sorted({(item.from_code, item.to_code) for item in package.get_available_packages()})
for source, target in pairs:
    print(f"{source} -> {target}")
PY
```

Команда обращается только к каталогу моделей; пользовательский текст никуда не
отправляется.

## Просмотр установленных пакетов

```bash
python - <<'PY'
from argostranslate import package

for item in package.get_installed_packages():
    print(f"{item.from_code} -> {item.to_code} ({item.package_version})")
PY
```

## Установка из заранее скачанного файла

Тяжёлые файлы моделей не следует сохранять в Git. Передайте путь к файлу
`.argosmodel`, находящемуся вне репозитория:

```bash
python scripts/install_argos_model.py \
  --from en \
  --to ru \
  --model-file /path/to/translate-en_ru.argosmodel \
  --sbd-model-file /path/to/en.onnx
```

`--sbd-model-file` нужен для первого запуска без доступа к сети. При обычной
установке скрипт самостоятельно загружает совместимую MiniSBD-модель.

## Где хранятся модели

Argos хранит пакеты в пользовательском каталоге данных вне репозитория. Узнать
конкретные пути для текущей системы:

```bash
python - <<'PY'
from argostranslate import sbd, settings

print("Argos packages:", settings.package_data_dir)
print("MiniSBD cache:", sbd.minisbd_models.cache_dir)
PY
```

Репозиторий игнорирует `*.argosmodel`, `*.onnx`, каталоги `models/` и
`model-cache/`, защищая первый коммит и последующие push от тяжёлых файлов.
