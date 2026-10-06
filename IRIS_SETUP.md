# ВАЖНО: версия наказаний ЧЕРЕЗ IRIS

В этой сборке BroMeloMod НЕ выдаёт мут/варн/бан напрямую через Telegram.

Он:
1. находит нарушение;
2. отвечает на сообщение нарушителя командой, адресованной Iris;
3. Iris выдаёт варн / мут / кик / бан;
4. через несколько секунд команда BroMeloMod и исходное нарушение удаляются;
5. сообщение о наказании остаётся уже от Iris.

По умолчанию:
IRIS_BOT_USERNAME=iris_cm_bot

Если у тебя в группе другой Iris, например `@iris_dp_bot`,
поставь в Render Environment:
IRIS_BOT_USERNAME=iris_dp_bot

## ОБЯЗАТЕЛЬНО 1 — Bot-to-Bot Communication

Telegram обычно не отдаёт ботам сообщения других ботов.
Новый режим Bot-to-Bot позволяет это для сообщений-команд,
явно адресованных другому боту.

В @BotFather открой настройки BroMeloMod и включи
Bot-to-Bot Communication Mode.

Если этот режим выключен, Iris не увидит команды BroMeloMod.

## ОБЯЗАТЕЛЬНО 2 — дать BroMeloMod ранг в Iris

Iris проверяет ранг автора команды.

От владельца/создателя чата выдай своему боту ранг Iris.
Например:
+Модер 4 @USERNAME_ТВОЕГО_БОТА

Проверить ранги можно стандартными командами Iris.

## ОБЯЗАТЕЛЬНО 3 — сам Iris должен быть в группе

Официальный основной Iris:
@iris_cm_bot

Он должен быть администратором с правами модерации.

## Какие команды отправляет BroMeloMod

Первое обычное нарушение:
`/warn@iris_cm_bot`

Повтор:
`/mute@iris_cm_bot 6ч`

Следующее:
`/mute@iris_cm_bot 1д`

Дальше:
`/ban@iris_cm_bot`

Спам и правило Павловой используют свою лестницу наказаний из проекта.

Причина отправляется на следующей строке.

## Render Environment

Добавь:
IRIS_BOT_USERNAME=iris_cm_bot
IRIS_COMMAND_DELETE_SECONDS=6

Если у тебя `@iris_dp_bot`, замени значение на:
IRIS_BOT_USERNAME=iris_dp_bot

## После загрузки

1. Upload/commit новые файлы.
2. Render -> Manual Deploy -> Deploy latest commit.
3. В группе `/activate`.
4. Проверь тестовым нарушением.
5. В логах при проблеме ищи `IRIS SEND ERROR`.
