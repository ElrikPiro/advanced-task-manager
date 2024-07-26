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
from src.ActiveTaskFilter import InactiveTaskFilter

if __name__ == '__main__':

    # IoC

    ## environment variables
    token = getenv("TELEGRAM_BOT_TOKEN")
    chatId = getenv("TELEGRAM_CHAT_ID")
    vaultPath = getenv("OBSIDIAN_VAULT_PATH")

    ## telegram bot
    bot : telegram.Bot = telegram.Bot(token)

    ## task provider
    jsonLoader = JsonLoader()
    taskJsonProvider = ObsidianDataviewTaskJsonProvider(jsonLoader)
    taskProvider = ObsidianTaskProvider(taskJsonProvider, vaultPath)

    ## heuristics
    heuristicList = [
        ("Remaining Effort(1)", RemainingEffortHeuristic(taskProvider, 1.0)),
        ("Remaining Effort(5)", RemainingEffortHeuristic(taskProvider, 5.0)),
        ("Remaining Effort(10)", RemainingEffortHeuristic(taskProvider, 10.0)),
        ("Slack Heuristic", SlackHeuristic(taskProvider)),
        ("Tomorrow Slack Heuristic", TomorrowSlackHeuristic(taskProvider)),
    ]

    ## filters
    activeFilter = ActiveTaskFilter()
    orderedHeuristics = [
        (TomorrowSlackHeuristic(taskProvider), 100.0),
        (SlackHeuristic(taskProvider), 10.0),
        (SlackHeuristic(taskProvider), 5.0),
    ]
    defaultHeuristic = (SlackHeuristic(taskProvider), 1.0)
    
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
        ("All inactive task filter", InactiveTaskFilter()),
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
## 10. Eliminar tomorrow slack heuristic y en su lugar crear la heuristica de DaysToThresholdHeuristic
## 11.  a�adir get task extended info que extraiga las lineas del fichero posteriores a la l�nea de la tarea