#!/bin/bash
# Запуск бота с секретами из .env. Без аргументов: бот отвечает на команды.
# С аргументами они передаются боту, например: ./run_bot.sh --send-morning --dry-run
cd "$(dirname "$0")" || exit 1
set -a
. ./.env
set +a
export TZ="Europe/Moscow"
exec python3 telegram_bot.py "$@"
