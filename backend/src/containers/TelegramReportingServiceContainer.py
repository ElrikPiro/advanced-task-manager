from dependency_injector import containers, providers
import telegram

from src.TelegramTaskListManager import TelegramTaskListManager
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
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.filters.ContextPrefixTaskFilter import ContextPrefixTaskFilter
from src.filters.GtdTaskFilter import GtdTaskFilter
from src.filters.ActiveTaskFilter import InactiveTaskFilter
from src.heuristics.DaysToThresholdHeuristic import DaysToThresholdHeuristic
from src.StatisticsService import StatisticsService
from src.FileBroker import FileBroker
from src.filters.WorkloadAbleFilter import WorkloadAbleFilter


class TelegramReportingServiceContainer():

    # tries to get a configuration value from the environment, if not present
    # then it will try to get it from the json configuration file
    def tryGetConfig(self, key: str, required: bool = False, default: str = None) -> str:
        self.config.query.from_env(key, as_=str, required=False, default=None)
        value = None if self.config.query() == "None" else self.config.query()
        if value is None:
            value = self.config.jsonConfig[key]()
        if value is None and required:
            raise ValueError(f"Configuration value {key} is required")
        elif value is None:
            return default
        return value

    def __init__(self):
        self.container = containers.DynamicContainer()
        self.config = providers.Configuration()

        # Configuration
        self.config.jsonConfig.from_json("config.json", required=True)

        # Configuration values
        configMode: int = int(self.tryGetConfig("APP_MODE", True))
        telegramMode = configMode >= 0
        obsidianMode = configMode == 1

        jsonPath = self.tryGetConfig("JSON_PATH", True)

        token = self.tryGetConfig("TELEGRAM_BOT_TOKEN", telegramMode, default="NULL_TOKEN")
        chatId = self.tryGetConfig("TELEGRAM_CHAT_ID", telegramMode, default="0")

        appdata = self.tryGetConfig("APPDATA", obsidianMode, default="NULL_APPDATA")
        vaultPath = self.tryGetConfig("OBSIDIAN_VAULT_PATH", obsidianMode, default="NULL_VAULT_PATH")

        categoriesConfigOption = self.config.jsonConfig.categories()
        self.container.categories = list[dict](categoriesConfigOption)

        # External services

        ## Telegram bots
        self.container.bot = providers.Singleton(telegram.Bot, token=token)

        # Data providers
        self.container.fileBroker = providers.Singleton(FileBroker, jsonPath, appdata, vaultPath)

        # User communication services
        self.container.shellUserCommService = providers.Singleton(ShellUserCommService, chatId)
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
        self.container.tomorrowSlackHeuristic = providers.Factory(SlackHeuristic, self.container.taskProvider, 1)

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

        # Task Manager
        self.container.taskListManager = providers.Singleton(TelegramTaskListManager, self.container.taskProvider().getTaskList(), self.container.heuristicList, self.container.filterList, self.container.statisticsService)

        # Reporting service
        self.container.telegramReportingService = providers.Singleton(TelegramReportingService, self.container.userCommService(), self.container.taskProvider(), self.container.heristicScheduling(), self.container.statisticsService(), self.container.taskListManager(), self.container.categories, chatId)
