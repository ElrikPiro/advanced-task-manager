from dependency_injector import containers, providers
import telegram
import os

from src.wrappers.TelegramBotUserCommService import TelegramBotUserCommService
from src.wrappers.ShellUserCommService import ShellUserCommService
from src.taskproviders.TaskProvider import TaskProvider
from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.HeuristicScheduling import HeuristicScheduling
from src.filters.ActiveTaskFilter import ActiveTaskFilter
from src.TelegramReportingService import TelegramReportingService
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.taskjsonproviders.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.heuristics.SlackHeuristic import SlackHeuristic
from src.heuristics.TomorrowSlackHeuristic import TomorrowSlackHeuristic
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.filters.ContextPrefixTaskFilter import ContextPrefixTaskFilter
from src.filters.GtdTaskFilter import GtdTaskFilter
from src.filters.ActiveTaskFilter import InactiveTaskFilter
from src.heuristics.DaysToThresholdHeuristic import DaysToThresholdHeuristic
from src.StatisticsService import StatisticsService
from src.FileBroker import FileBroker
from src.filters.WorkloadAbleFilter import WorkloadAbleFilter

from src.Interfaces.IFilter import IFilter

class TelegramReportingServiceContainer():

    def __init__(self):
        self.container = containers.DynamicContainer()
        self.config = providers.Configuration()

        # Configuration
        self.config.mode.from_env("APP_MODE", as_=str, required=True)
        configMode : int = int(self.config.mode())
        telegramMode = configMode >= 0
        obsidianMode = configMode == 1

        ## Environment variables
        self.config.jsonPath.from_env("JSON_PATH", as_=str, required=True)

        self.config.token.from_env("TELEGRAM_BOT_TOKEN", as_=str, required=telegramMode, default="NULL_TOKEN")
        self.config.chatId.from_env("TELEGRAM_CHAT_ID", as_=str, required=telegramMode, default="NULL_CHAT_ID")

        self.config.appdata.from_env("APPDATA", as_=str, required=obsidianMode, default="NULL_APPDATA")
        self.config.vaultPath.from_env("OBSIDIAN_VAULT_PATH", as_=str, required=obsidianMode, default="NULL_VAULT_PATH")

        ## Configuration file
        self.config.jsonConfig.from_json("config.json", required=True)
        
        self.container.categories : list[dict] = self.config.jsonConfig.categories()

        # External services

        ## Telegram bots
        self.container.bot = providers.Singleton(telegram.Bot, token=self.config.token)

        # Data providers
        self.container.fileBroker = providers.Singleton(FileBroker, self.config.jsonPath, self.config.appdata, self.config.vaultPath)

        ## User communication services
        self.container.shellUserCommService = providers.Singleton(ShellUserCommService, self.config.chatId)
        self.container.telegramUserCommService = providers.Singleton(TelegramBotUserCommService, self.container.bot, self.container.fileBroker)
        
        self.container.userCommService = self.container.telegramUserCommService if telegramMode else self.container.shellUserCommService

        if obsidianMode:
            self.container.taskJsonProvider = providers.Singleton(ObsidianDataviewTaskJsonProvider, self.container.fileBroker)
            self.container.taskProvider = providers.Singleton(ObsidianTaskProvider, self.container.taskJsonProvider, self.container.fileBroker)
        else:
            self.container.taskJsonProvider = providers.Singleton(TaskJsonProvider, self.container.fileBroker)
            self.container.taskProvider = providers.Singleton(TaskProvider, self.container.taskJsonProvider, self.container.fileBroker)
        # Heuristics
        self.container.remainingEffortHeuristic = providers.Factory(RemainingEffortHeuristic, self.container.taskProvider)
        self.container.daysToThresholdHeuristic = providers.Factory(DaysToThresholdHeuristic, self.container.taskProvider)
        self.container.slackHeuristic = providers.Factory(SlackHeuristic, self.container.taskProvider)
        self.container.tomorrowSlackHeuristic = providers.Factory(TomorrowSlackHeuristic, self.container.taskProvider)

        ## Heuristic list
        self.container.heuristicList = providers.List(
            ("Remaining Effort(1)", self.container.remainingEffortHeuristic(1.0)),
            ("Remaining Time(100)", self.container.daysToThresholdHeuristic(100.0)),
            ("Remaining Time(1)", self.container.daysToThresholdHeuristic(1.0)),
            ("Slack Heuristic", self.container.slackHeuristic()),
        )

        # Filters
        self.container.activeFilter = providers.Singleton(ActiveTaskFilter)
        
        self.container.contextPrefixTaskFilter = providers.Factory(ContextPrefixTaskFilter, self.container.activeFilter)
        
        self.container.orderedHeuristics = providers.List(
            (self.container.tomorrowSlackHeuristic(), 100.0),
            (self.container.slackHeuristic(), 10.0),
            (self.container.slackHeuristic(), 5.0),
        )

        self.container.defaultHeuristic = providers.Object((self.container.slackHeuristic(), 1.0))

        self.container.orderedCategories = []
        for categoryDict in self.container.categories:
            prefix = categoryDict["prefix"]
            description = categoryDict["description"]
            self.container.orderedCategories.append((description, self.container.contextPrefixTaskFilter(prefix=prefix)))

        self.container.gtdFilter = providers.Singleton(GtdTaskFilter, self.container.activeFilter(), self.container.orderedCategories, self.container.orderedHeuristics(), self.container.defaultHeuristic())

        self.container.workLoadAbleFilter = providers.Singleton(WorkloadAbleFilter, self.container.activeFilter())

        ## Filter list
        self.container.filterList = [
            ("GTD filter", self.container.gtdFilter()),
            ("All active task filter", self.container.activeFilter()),
            ("All inactive task filter", InactiveTaskFilter()),
        ]
        self.container.filterList.extend(self.container.orderedCategories)

        # Scheduling algorithm
        self.container.heristicScheduling = providers.Singleton(HeuristicScheduling, self.container.taskProvider())
        
        # Statistics service
        self.container.statisticsService = providers.Singleton(StatisticsService, self.container.fileBroker, self.container.workLoadAbleFilter, self.container.remainingEffortHeuristic(1.0), self.container.slackHeuristic)

        # Reporting service
        self.container.telegramReportingService = providers.Singleton(TelegramReportingService, self.container.userCommService, self.container.taskProvider, self.container.heristicScheduling, self.container.statisticsService, self.container.heuristicList, self.container.filterList, self.container.categories, self.config.chatId)
