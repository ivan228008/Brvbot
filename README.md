# BRV / Сглыпа — Render Webhook + PostgreSQL

Эта версия сделана специально для Render Web Service.

Главное отличие:
- бот больше НЕ использует polling;
- открывает HTTP-порт для Render;
- Telegram присылает сообщения через webhook;
- база PostgreSQL, поэтому варны / топ / история не зависят от локального диска Render;
- при каждом deploy Telegram pending updates удаляются (`drop_pending_updates=True`);
- `/activate` дополнительно фиксирует момент, раньше которого сообщения не учитываются.

## 1. PostgreSQL

Нужен PostgreSQL URL.

Подойдёт:
- Render PostgreSQL;
- Neon;
- Supabase PostgreSQL;
- любой PostgreSQL с обычным connection string.

Пример:
`postgresql://user:password@host:5432/database`

Сохрани его как Environment Variable:
`DATABASE_URL`

## 2. Render Web Service

Build Command:
`pip install -r requirements.txt`

Start Command:
`python main.py`

Health Check:
`/health`

Python:
файл `.python-version` уже задаёт Python 3.12.11.

## 3. Environment Variables

Обязательные:

`BOT_TOKEN`
токен от BotFather.

`OWNER_ID`
твой числовой Telegram ID.

`DATABASE_URL`
PostgreSQL connection string.

`WEBHOOK_BASE_URL`
URL именно твоего Render Web Service, например:
`https://brv-sglypa-moderator.onrender.com`

Не добавляй `/telegram/webhook` вручную — код добавит путь сам.

Дополнительные уже есть в render.yaml:
`BOT_NICKNAMES=сглыпа,sglypa,сглып`
`PAVLOVA_NAMES=павлова,pavlova,@pav.p3`

## 4. BotFather

Обязательно:
`/setprivacy` → выбрать бота → `Disable`

Иначе в группе Telegram не будет отдавать боту обычные сообщения.

## 5. Права бота в группе

Сделай администратором и выдай:
- Delete messages
- Ban users
- Restrict members

## 6. После успешного Deploy

Открой:
`https://ТВОЙ-СЕРВИС.onrender.com/health`

Должно показать JSON с:
`"ok": true`

После этого в Telegram-группе:
`/activate`

Бот ответит:
`База активирована с этого момента. Старые сообщения не учитываются.`

## 7. Что хранится в PostgreSQL

- участники;
- сообщения;
- репутация;
- нарушения;
- причина нарушения;
- дата;
- наказания;
- антиспам-история;
- время активации чата.

## 8. Команды

`/activate`
начинает учёт с текущего момента.

`/top`
топ активности + репутация.

`/stats`
статистика.

Админ может ответить `/stats` на сообщение пользователя.

`/history`
последние нарушения.

`/warn`
ручной варн ответом на сообщение.

`/mute 60`
мут ответом на сообщение.

`/ban`
бан ответом на сообщение.

`/clearwarns`
очистить историю нарушений пользователя.

## 9. Бесплатный Render

Free Web Service может засыпать при отсутствии HTTP-трафика.
При следующем Telegram webhook Render проснётся, поэтому первая обработка после долгого простоя
может быть заметно медленнее.

ПК пользователя при этом вообще не нужен.
