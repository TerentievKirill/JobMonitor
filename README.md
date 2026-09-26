# Job Monitor

Автономный сборщик вакансий из пользовательской папки Telegram. Подключается как
обычный аккаунт через Telethon, раз в час читает новые публикации и складывает их
в SQLite.

Сервис не скачивает медиа, не открывает внешние ссылки и ничего не отправляет в
Telegram. Внешние порты не используются.

## Как устроены данные

SQLite хранит все полученные сообщения в таблице `messages`. Это позволяет
улучшить фильтры и повторно обработать историю без новой загрузки из Telegram.

SQL-view `vacancies` содержит только сообщения, которые:

- не являются явными резюме, рекламой или статьями;
- не являются точным повтором уже сохранённой публикации.

Фильтр намеренно консервативный: если он сомневается, сообщение остаётся в
`vacancies`.

Основные файлы в `data/`:

- `collector.session` — авторизованная Telegram-сессия;
- `vacancies.db` — SQLite-база;
- `vacancies.json` — необязательный экспорт чистой ленты.

Файлы `.env`, `*.session` и базу нельзя публиковать в Git.

## Локальный запуск

Нужен Python 3.11 или новее.

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

В `.env` заполнить:

```dotenv
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
```

### Авторизация

```bash
python main.py auth
```

В консоли появится QR-код. На телефоне открыть:

```text
Telegram → Настройки → Устройства → Подключить устройство
```

После сканирования сессия сохранится в `data/collector.session`.

### Один сбор

```bash
python main.py collect-once
```

При первом запуске загружаются публикации за последние 72 часа. Следующие
запуски используют максимальный `message_id` каждого источника и получают только
новые сообщения.

Повторный запуск безопасен: уникальный ключ `(channel_id, message_id)` не даёт
записать одно Telegram-сообщение дважды.

### Постоянная работа

```bash
python main.py run
```

По умолчанию новый цикл начинается раз в час. Интервал задаётся в `.env`:

```dotenv
POLL_INTERVAL_SECONDS=3600
```

### Статистика и экспорт

```bash
python main.py stats
python main.py export
```

Экспорт создаёт `data/vacancies.json` из SQL-view `vacancies`.

## Docker

Контейнер не публикует порты и не конфликтует с другими сервисами на VPS.
Каталог `./data` подключается внутрь контейнера и переживает пересоздание.

Сначала выполнить интерактивную авторизацию:

```bash
docker-compose run --rm app python main.py auth
```

Затем запустить постоянный сбор:

```bash
docker-compose up -d --build
docker-compose logs -f app
```

Полезные команды:

```bash
docker-compose run --rm app python main.py collect-once
docker-compose run --rm app python main.py stats
docker-compose run --rm app python main.py export
docker-compose down
```

Остановка контейнера не удаляет `data/vacancies.db` и Telegram-сессию.

## Перенос на VPS

Если авторизация уже выполнена локально, можно безопасно скопировать весь проект
на VPS вместе с `data/collector.session`, не проходя QR-вход снова. Session-файл
нужно передавать только по защищённому каналу и хранить как секрет.

На сервере:

```bash
cp .env.example .env
# заполнить .env
docker-compose up -d --build
```

Для проекта не нужны `ports:` и отдельный PostgreSQL-контейнер.

## Конфигурация

| Переменная | По умолчанию | Назначение |
|---|---:|---|
| `TELEGRAM_FOLDER` | `Поиск работы` | Папка с источниками |
| `DATABASE_PATH` | `data/vacancies.db` | SQLite-файл |
| `INITIAL_HOURS_BACK` | `72` | Глубина первой загрузки |
| `INITIAL_MAX_MESSAGES_PER_CHAT` | `500` | Лимит первой загрузки канала |
| `MAX_MESSAGES_PER_CHAT_PER_RUN` | `1000` | Лимит догрузки за цикл |
| `POLL_INTERVAL_SECONDS` | `3600` | Интервал сбора |
| `STORE_RAW_JSON` | `true` | Хранить исходный объект Telethon |

Если база начинает занимать слишком много места, можно установить:

```dotenv
STORE_RAW_JSON=false
```

Текст, ссылки и все поля, необходимые будущему боту и рекомендательной системе,
продолжат сохраняться.

## Тесты

```bash
pip install -r requirements-dev.txt
pytest
```

Проверяются консервативная фильтрация, отсутствие дублей при повторном запуске,
поиск одинаковых публикаций в разных каналах и формирование view `vacancies`.

## Старые команды

`python collector.py` оставлен как совместимый псевдоним для одного сбора.
`filter_vacancies.py` можно использовать для старых выгрузок `messages.jsonl`.
