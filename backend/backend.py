from os import getenv

import telegram

from src.ActiveTaskFilter import ActiveTaskFilter
from src.TelegramReportingService import TelegramReportingService
from src.ObsidianTaskProvider import ObsidianTaskProvider
from src.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.JsonLoader import JsonLoader
from src.SlackHeuristic import SlackHeuristic
from src.TomorrowSlackHeuristic import TomorrowSlackHeuristic
from src.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.ContextPrefixTaskFilter import ContextPrefixTaskFilter
from src.GtdTaskFilter import GtdTaskFilter

if __name__ == '__main__':

    # IoC
    ## constants
    pomodorosPerDay = 2.6

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
        ("Tomorrow Slack Heuristic", TomorrowSlackHeuristic(pomodorosPerDay)),
        ("Remaining Effort(1)", RemainingEffortHeuristic(pomodorosPerDay, 1.0)),
        ("Remaining Effort(5)", RemainingEffortHeuristic(pomodorosPerDay, 5.0)),
        ("Remaining Effort(10)", RemainingEffortHeuristic(pomodorosPerDay, 10.0)),
    ]

    ## filters
    activeFilter = ActiveTaskFilter()
    orderedHeuristics = [
        (TomorrowSlackHeuristic(pomodorosPerDay), 100.0),
        (SlackHeuristic(pomodorosPerDay), 10.0),
        (SlackHeuristic(pomodorosPerDay), 5.0),
    ]
    defaultHeuristic = (SlackHeuristic(pomodorosPerDay), 1.0)
    
    orderedCategories = [
        ("Bullet journal filter", ContextPrefixTaskFilter(activeFilter, "bujo")),
        ("Indoor task filter", ContextPrefixTaskFilter(activeFilter, "indoor_")),
        ("Device-specific tasks filter", ContextPrefixTaskFilter(activeFilter, "aux_device_")),
        ("Computer task filter", ContextPrefixTaskFilter(activeFilter, "workstation")),
        ("Outdoor task filter", ContextPrefixTaskFilter(activeFilter, "outdoor_")),
    ]
    gtdFilter = GtdTaskFilter(activeFilter, orderedCategories, orderedHeuristics, defaultHeuristic)

    filterList = [
        ("GTD filter", gtdFilter),
        ("All active task filter", activeFilter),
        ("Bullet journal filter", ContextPrefixTaskFilter(activeFilter, "bujo")),
        ("Indoor task filter", ContextPrefixTaskFilter(activeFilter, "indoor_")),
        ("Device-specific tasks filter", ContextPrefixTaskFilter(activeFilter, "aux_device_")),
        ("Computer task filter", ContextPrefixTaskFilter(activeFilter, "workstation")),
        ("Outdoor task filter", ContextPrefixTaskFilter(activeFilter, "outdoor_")),
    ]

    service = TelegramReportingService(bot, taskProvider, heuristicList, filterList, chatId)
    service.listenForEvents()
    pass

# TODO: Roadmap
## 8. Pomodoros per day autoupdate
## 9. Fix out of bounds page list