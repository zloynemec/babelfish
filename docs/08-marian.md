# MarianMT через CTranslate2

Provider `marian` использует открытые модели MarianMT/OPUS-MT и выполняет inference
локально через CTranslate2. Hugging Face нужен только для загрузки исходной модели;
текст запросов туда не отправляется.

## Установка модели

После установки Python-зависимостей проекта выполните:

```bash
python scripts/install_marian_model.py --from en --to ru
```

По умолчанию используется модель `Helsinki-NLP/opus-mt-en-ru`, а веса
конвертируются в `int8`. Каталог назначения задаётся `MARIAN_MODELS_DIR` и по
умолчанию равен `~/.local/share/babelfish/marian`.

Для другой пары:

```bash
python scripts/install_marian_model.py --from en --to de
```

Если имя модели нельзя вывести как `Helsinki-NLP/opus-mt-SOURCE-TARGET`, задайте
его явно:

```bash
python scripts/install_marian_model.py \
  --from en \
  --to fr \
  --model-id Helsinki-NLP/opus-mt-en-fr
```

`--model-id` также принимает путь к заранее загруженному локальному Transformers
model directory. В этом режиме установщик не обращается к Hugging Face.

Для замены установленной пары используйте `--force`. Доступные схемы quantization:

```bash
python scripts/install_marian_model.py \
  --from en \
  --to ru \
  --quantization int8 \
  --force
```

## Запуск и запрос

```bash
uvicorn translation_service.main:app --host 0.0.0.0 --port 8000
```

```bash
curl -X POST http://localhost:8000/v1/translate \
  -H 'Content-Type: application/json' \
  -d '{
    "text": "A collection of media links about air quality research",
    "source_language": "en",
    "target_language": "ru",
    "translator": "marian"
  }'
```

`GET /v1/translators` показывает все обнаруженные Marian-пары. После установки
новой модели перезапустите процесс, чтобы гарантированно выгрузить старый runtime.

## Конфигурация runtime

```env
MARIAN_MODELS_DIR=~/.local/share/babelfish/marian
MARIAN_DEVICE=cpu
MARIAN_COMPUTE_TYPE=int8
```

Для NVIDIA GPU используйте `MARIAN_DEVICE=cuda` и совместимую compute type. Набор
доступных compute types зависит от устройства и сборки CTranslate2.

## Формат установленной модели

Установщик создаёт отдельный каталог для каждой пары:

```text
~/.local/share/babelfish/marian/
└── en-ru/
    ├── babelfish-model.json
    ├── model/
    └── tokenizer/
```

В Git эти каталоги добавлять не нужно. Исходные веса и CTranslate2 `model.bin`
являются тяжёлыми runtime-артефактами.
