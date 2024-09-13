from dependency_injector import containers, providers
import telegram

from src.wrappers.TelegramBotUserCommService import TelegramBotUserCommService
from src.TaskProvider import TaskProvider
from src.TaskJsonProvider import TaskJsonProvider
from src.HeuristicScheduling import HeuristicScheduling
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
from src.DaysToThresholdHeuristic import DaysToThresholdHeuristic

class TelegramReportingServiceContainer():

    def __init__(self):
        self.container = containers.DynamicContainer()
        self.config = providers.Configuration()

        # Configuration
        self.config.mode.from_env("APP_MODE", as_=str, required=True)
        self.config.token.from_env("TELEGRAM_BOT_TOKEN", as_=str, required=True)
        self.config.chatId.from_env("TELEGRAM_CHAT_ID", as_=str, required=True)
        if self.config.mode() == "1":
            self.config.vaultPath.from_env("OBSIDIAN_VAULT_PATH", as_=str, required=True)
        elif self.config.mode() == "0":
            self.config.jsonPath.from_env("JSON_PATH", as_=str, required=True)
        else:
            raise ValueError("Invalid mode " + self.config.mode())

        # External services
        self.container.bot = providers.Singleton(telegram.Bot, token=self.config.token)
        self.container.telegramBotUserCommService = providers.Singleton(TelegramBotUserCommService, self.container.bot)
        
        # Data providers
        self.container.jsonLoader = providers.Singleton(JsonLoader)

        if self.config.mode() == "1":
            self.container.taskJsonProvider = providers.Singleton(ObsidianDataviewTaskJsonProvider, self.container.jsonLoader)
            self.container.taskProvider = providers.Singleton(ObsidianTaskProvider, self.container.taskJsonProvider, self.config.vaultPath)
        elif self.config.mode() == "0":
            self.container.taskJsonProvider = providers.Singleton(TaskJsonProvider, self.config.jsonPath, self.container.jsonLoader)
            self.container.taskProvider = providers.Singleton(TaskProvider, self.container.taskJsonProvider)
        # Heuristics
        self.container.remainingEffortHeuristic = providers.Factory(RemainingEffortHeuristic, self.container.taskProvider)
        self.container.daysToThresholdHeuristic = providers.Factory(DaysToThresholdHeuristic, self.container.taskProvider)
        self.container.slackHeuristic = providers.Factory(SlackHeuristic, self.container.taskProvider)
        self.container.tomorrowSlackHeuristic = providers.Factory(TomorrowSlackHeuristic, self.container.taskProvider)

        ## Heuristic list
        self.container.heuristicList = providers.List(
            ("Remaining Effort(1)", self.container.remainingEffortHeuristic(1.0)),
            ("Remaining Effort(5)", self.container.remainingEffortHeuristic(5.0)),
            ("Remaining Effort(10)", self.container.remainingEffortHeuristic(10.0)),
            ("Remaining Time(100)", self.container.daysToThresholdHeuristic(100.0)),
            ("Remaining Time(5)", self.container.daysToThresholdHeuristic(5.0)),
            ("Remaining Time(1)", self.container.daysToThresholdHeuristic(1.0)),
            ("Slack Heuristic", self.container.slackHeuristic()),
            ("Tomorrow Slack Heuristic", self.container.tomorrowSlackHeuristic()),
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

        self.container.orderedCategories = providers.List(
            ("Bullet journal filter", self.container.contextPrefixTaskFilter(prefix="bujo")),
            ("Indoor task filter", self.container.contextPrefixTaskFilter(prefix="indoor")),
            ("Device-specific task filter", self.container.contextPrefixTaskFilter(prefix="aux_device")),
            ("Computer task filter", self.container.contextPrefixTaskFilter(prefix="workstation")),
            ("Outdoor task filter", self.container.contextPrefixTaskFilter(prefix="outdoor")),
        )

        self.container.gtdFilter = providers.Singleton(GtdTaskFilter, self.container.activeFilter(), self.container.orderedCategories(), self.container.orderedHeuristics(), self.container.defaultHeuristic())

        ## Filter list
        self.container.filterList = providers.List(
            ("GTD filter", self.container.gtdFilter()),
            ("All active task filter", self.container.activeFilter()),
            ("All inactive task filter", InactiveTaskFilter()),
            ("Bullet journal filter", self.container.contextPrefixTaskFilter(prefix="bujo")),
            ("Indoor task filter", self.container.contextPrefixTaskFilter(prefix="indoor")),
            ("Device-specific task filter", self.container.contextPrefixTaskFilter(prefix="aux_device")),
            ("Computer task filter", self.container.contextPrefixTaskFilter(prefix="workstation")),
            ("Outdoor task filter", self.container.contextPrefixTaskFilter(prefix="outdoor")),
        )

        # Scheduling algorithm
        self.container.heristicScheduling = providers.Singleton(HeuristicScheduling, self.container.taskProvider())

        # Reporting service
        self.container.telegramReportingService = providers.Singleton(TelegramReportingService, self.container.telegramBotUserCommService, self.container.taskProvider, self.container.heristicScheduling, self.container.heuristicList, self.container.filterList, self.config.chatId)
