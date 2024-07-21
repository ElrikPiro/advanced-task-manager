from os import getenv

import telegram

from src.TelegramReportingService import TelegramReportingService
from src.ObsidianTaskProvider import ObsidianTaskProvider
from src.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.JsonLoader import JsonLoader

if __name__ == '__main__':

    # IoC
    ## telegram bot
    token = getenv("TELEGRAM_BOT_TOKEN")
    bot : telegram.Bot = telegram.Bot(token)

    ## task provider
    jsonLoader = JsonLoader()
    taskJsonProvider = ObsidianDataviewTaskJsonProvider(jsonLoader)
    taskProvider = ObsidianTaskProvider(taskJsonProvider)

    chatId = getenv("TELEGRAM_CHAT_ID")
    service = TelegramReportingService(bot, taskProvider, chatId)
    service.listenForEvents()
    pass