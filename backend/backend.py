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

# TODO: Roadmap
## 2. Add a list of heuristics to the TelegramReportingService so we can order the tasks based on different criteria
## 3. Create a IFilter interface to filter tasks based on different criteria
## 4. Create a FilterActiveTasks class that implements IFilter to filter only active tasks
## 5. Add a list of filters to the TelegramReportingService so we can filter the tasks based on different criteria
## 6. Create commands for both heuristics and filter selection at the telegram bot
## 7. Create a Heuristic and a Filter that implements the current strategy at GTD