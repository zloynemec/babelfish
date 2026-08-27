# Установка и запуск

## Требования

- Git;
- Python 3.12 или новее;
- доступ к интернету во время установки Python-зависимостей и языковых моделей.

После установки модели перевод выполняется локально. Сервис не отправляет
пользовательский текст внешним API и не имеет внешней квоты на количество переводов.

## 1. Получение исходного кода

```bash
git clone git@github.com:zloynemec/babelfish.git
cd babelfish
```

Если SSH-ключ GitHub не настроен, используйте HTTPS:

```bash
git clone https://github.com/zloynemec/babelfish.git
cd babelfish
```

## 2. Виртуальное окружение и зависимости

Linux/macOS:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Для разработки и запуска тестов установите dev dependencies:

```bash
python -m pip install -e '.[dev]'
```

## 3. Конфигурация

Значения по умолчанию уже подходят для локального запуска. При необходимости
создайте `.env` из примера:

```bash
cp .env.example .env
```

Переменные:

| Переменная | Default | Назначение |
| --- | --- | --- |
| `APP_HOST` | `0.0.0.0` | Адрес HTTP-сервера |
| `APP_PORT` | `8000` | Порт HTTP-сервера |
| `LOG_LEVEL` | `INFO` | Уровень логирования |
| `DEFAULT_TRANSLATOR` | `argos` | Provider по умолчанию |
| `DEFAULT_SOURCE_LANGUAGE` | `en` | Исходный язык по умолчанию |
| `MAX_TEXT_LENGTH` | `20000` | Максимальная длина текста |
| `TRANSLATION_TIMEOUT_SECONDS` | `30` | Timeout одного перевода |

## 4. Подключение Argos Translate

Python-пакет Argos устанавливается вместе с проектом. Для выполнения переводов
нужно отдельно установить хотя бы одну языковую модель, например `en -> ru`:

```bash
python scripts/install_argos_model.py --from en --to ru
```

Скрипт скачивает модель из публичного каталога Argos и устанавливает её в
пользовательское хранилище Argos, а не в Git-репозиторий. Текущий путь можно узнать:

```bash
python -c "from argostranslate import settings; print(settings.package_data_dir)"
```

Подробности об установке других пар и работе без сети описаны в
[инструкции по языкам Argos](07-argos-languages.md).

## 5. Запуск

```bash
uvicorn translation_service.main:app --host 0.0.0.0 --port 8000
```

Проверка:

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl -X POST http://localhost:8000/v1/translate \
  -H 'Content-Type: application/json' \
  -d '{"text":"Hello world","target_language":"ru"}'
```

Интерактивная документация Scalar: <http://localhost:8000/docs>.

## 6. Проверки для разработчика

```bash
ruff check .
pytest
```

Argos integration test автоматически пропускается, если модель `en -> ru` не
установлена. Тесты API не скачивают модели и используют fake provider.

## Обновление проекта

```bash
git pull
source .venv/bin/activate
python -m pip install -e '.[dev]'
```
