from os import getenv

import telegram

from src.TelegramReportingService import TelegramReportingService
from src.ObsidianTaskProvider import ObsidianTaskProvider
from src.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.JsonLoader import JsonLoader
from src.SlackHeuristic import SlackHeuristic
from src.RemainingEffortHeuristic import RemainingEffortHeuristic

if __name__ == '__main__':

    # IoC
    ## telegram bot
    token = getenv("TELEGRAM_BOT_TOKEN")
    bot : telegram.Bot = telegram.Bot(token)

    ## task provider
    jsonLoader = JsonLoader()
    taskJsonProvider = ObsidianDataviewTaskJsonProvider(jsonLoader)
    taskProvider = ObsidianTaskProvider(taskJsonProvider)

    ## heuristics
    heuristicList = [
        ("Slack Heuristic", SlackHeuristic(2.0)), 
        ("Remaining Effort(1)", RemainingEffortHeuristic(2.0, 1.0)),
        ("Remaining Effort(5)", RemainingEffortHeuristic(2.0, 5.0)),
        ("Remaining Effort(10)", RemainingEffortHeuristic(2.0, 10.0)),
    ]

    chatId = getenv("TELEGRAM_CHAT_ID")
    service = TelegramReportingService(bot, taskProvider, heuristicList, chatId)
    service.listenForEvents()
    pass

# TODO: Roadmap
## 3. Create a IFilter interface to filter tasks based on different criteria
## 4. Create a FilterActiveTasks class that implements IFilter to filter only active tasks
## 5. Add a list of filters to the TelegramReportingService so we can filter the tasks based on different criteria
## 6. Create commands for both heuristics and filter selection at the telegram bot
## 7. Create a Heuristic and a Filter that implements the current strategy at GTD