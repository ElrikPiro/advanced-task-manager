from os import getenv

import telegram

from src.ActiveTaskFilter import ActiveTaskFilter
from src.TelegramReportingService import TelegramReportingService
from src.ObsidianTaskProvider import ObsidianTaskProvider
from src.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.JsonLoader import JsonLoader
from src.SlackHeuristic import SlackHeuristic
from src.RemainingEffortHeuristic import RemainingEffortHeuristic

if __name__ == '__main__':

    # IoC
    ## constants
    pomodorosPerDay = 2.49

    ## telegram bot
    token = getenv("TELEGRAM_BOT_TOKEN")
    bot : telegram.Bot = telegram.Bot(token)
    chatId = getenv("TELEGRAM_CHAT_ID")

    ## task provider
    jsonLoader = JsonLoader()
    taskJsonProvider = ObsidianDataviewTaskJsonProvider(jsonLoader)
    taskProvider = ObsidianTaskProvider(taskJsonProvider)

    ## heuristics
    heuristicList = [
        ("Slack Heuristic", SlackHeuristic(pomodorosPerDay)), 
        ("Remaining Effort(1)", RemainingEffortHeuristic(pomodorosPerDay, 1.0)),
        ("Remaining Effort(5)", RemainingEffortHeuristic(pomodorosPerDay, 5.0)),
        ("Remaining Effort(10)", RemainingEffortHeuristic(pomodorosPerDay, 10.0)),
    ]

    ## filters
    filterList = [
        ("Active task filter", ActiveTaskFilter())
    ]

    service = TelegramReportingService(bot, taskProvider, heuristicList, filterList, chatId)
    service.listenForEvents()
    pass

# TODO: Roadmap
## 6. Create commands for both heuristics and filter selection at the telegram bot
## 7. Create a Heuristic and a Filter that implements the current strategy at GTD
## 8. Pomodoros per day autoupdate