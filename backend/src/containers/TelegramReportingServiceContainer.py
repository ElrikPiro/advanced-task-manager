import json
import os
from dependency_injector import containers, providers
import telegram

from src.wrappers.TimeManagement import TimeAmount
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
from src.TelegramTaskListManager import TelegramTaskListManager
from src.wrappers.TelegramBotUserCommService import TelegramBotUserCommService
from src.wrappers.ShellUserCommService import ShellUserCommService
from src.taskproviders.TaskProvider import TaskProvider
from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.HeuristicScheduling import HeuristicScheduling
from src.filters.ActiveTaskFilter import ActiveTaskFilter
from src.TelegramReportingService import TelegramReportingService
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.heuristics.SlackHeuristic import SlackHeuristic
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.filters.ContextPrefixTaskFilter import ContextPrefixTaskFilter
from src.filters.GtdTaskFilter import GtdTaskFilter
from src.filters.ActiveTaskFilter import InactiveTaskFilter
from src.heuristics.DaysToThresholdHeuristic import DaysToThresholdHeuristic
from src.StatisticsService import StatisticsService
from src.FileBroker import FileBroker
from src.filters.WorkloadAbleFilter import WorkloadAbleFilter
from src.ProjectManager import ObsidianProjectManager
from src.JsonProjectManager import JsonProjectManager


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

    def createDefaultConfig(self):
        # create a dict with the default config for categories
        defaultConfig = {
            "categories": [
                {
                    "prefix": "alert",
                    "description": "Alert and events"
                },
                {
                    "prefix": "billable",
                    "description": "Tasks that generate income"
                },
                {
                    "prefix": "indoor",
                    "description": "Indoor dynamic tasks"
                },
                {
                    "prefix": "aux_device",
                    "description": "Lightweight digital/analogic tasks"
                },
                {
                    "prefix": "bujo",
                    "description": "Bullet journal tasks"
                },
                {
                    "prefix": "workstation",
                    "description": "Heavyweight digital tasks"
                },
                {
                    "prefix": "outdoor",
                    "description": "Outdoor dynamic tasks"
                },
                {
                    "prefix": "inbox",
                    "description": "Inbox tasks"
                }
            ],
        }

        # ask the user for an app mode
        appMode = None
        while appMode not in ["1", "2", "3", "4"]:
            print("Please select an app mode:")
            print("\t1 - Obsidian (cmd)")
            print("\t2 - JSON file (cmd)")
            print("\t3 - JSON file (telegram)")
            print("\t4 - Obsidian (telegram)")
            appMode = input("App mode: ")
        defaultConfig["APP_MODE"] = appMode

        # ask the user for a json path
        jsonPath = input("Please enter the directory for saving data files: ")
        while not os.path.exists(jsonPath):
            print("That directory does not exist, using current directory")
            jsonPath = "."
        defaultConfig["JSON_PATH"] = jsonPath

        if appMode in ["3", "4"]:
            # ask the user for a telegram bot token
            telegramToken = input("Please enter the telegram bot token: ")
            defaultConfig["TELEGRAM_BOT_TOKEN"] = telegramToken

            # ask the user for a telegram chat id
            telegramChatId = input("Please enter the telegram chat id: ")
            defaultConfig["TELEGRAM_CHAT_ID"] = telegramChatId

        # if os not windows
        if os.name != "nt":
            # we keeping this for legacy reasons
            defaultConfig["APPDATA"] = jsonPath

        if appMode in ["1", "4"]:
            # ask the user for a vault path
            vaultPath = input("Please enter the markdown vault directory: ")
            while not os.path.exists(vaultPath):
                print("The directory does not exist, using current directory")
                vaultPath = "."
            defaultConfig["OBSIDIAN_VAULT_PATH"] = vaultPath
            # ask the user for a context missing policy
            print("Context missing policy is the policy to use when a task does not have a context")
            print("0 - ignore")
            print("1 - use_default")
            contextMissingPolicy = input("Please enter the context missing policy: (0)")
            while contextMissingPolicy not in ["0", "1"]:
                print("Invalid context missing policy, using 0 (ignore)")
                contextMissingPolicy = "0"
            defaultConfig["CONTEXT_MISSING_POLICY"] = contextMissingPolicy
            if contextMissingPolicy == "1":
                # ask the user for a default context
                defaultContext = input("Please enter the default context: ")
                # get a list of context categories prefixes
                contextCategories = [category["prefix"] for category in defaultConfig["categories"]]
                # check if the default context is in the list of prefixes
                while defaultContext not in contextCategories:
                    print(f"Invalid context, please select one of the following: {contextCategories}")
                    defaultContext = input("Please enter the default context: ")

                defaultConfig["DEFAULT_CONTEXT"] = defaultContext
            # ask the user for a date missing policy
            print("Date missing policy is the policy to use when a task does not have a valid date")
            print("0 - ignore")
            print("1 - use_current_date")
            dateMissingPolicy = input("Please enter the date missing policy: (0)")
            while dateMissingPolicy not in ["0", "1"]:
                print("Invalid date missing policy, using 0 (ignore)")
                dateMissingPolicy = "0"
            defaultConfig["DATE_MISSING_POLICY"] = dateMissingPolicy

        print("Dedication time is the minimum time you are willing to compromise to completing tasks, in minutes (i.e: 60m), hours (i.e: 1h), or pomodoros (i.e: 2.4p)")
        validPomodoros = False
        while not validPomodoros:
            dedicationTime = input("Please enter the dedication time: ")
            try:
                pomodorosPerDay = TimeAmount(dedicationTime)
                validPomodoros = TimeAmount(dedicationTime).as_pomodoros() > 0
            except Exception as e:
                print(f"Invalid pomodoro value: {e}")
                validPomodoros = False

        defaultConfig["DEDICATION_TIME"] = f"{pomodorosPerDay.as_pomodoros()}p"

        # write the default config to the config.json file in disk
        json.dump(defaultConfig, open("config.json", "w"), indent=4)

    def __init__(self):
        self.container = containers.DynamicContainer()
        self.config = providers.Configuration()

        # Configuration
        try:
            self.config.jsonConfig.from_json("config.json", required=True)
        except Exception as e:
            print(f"Error reading config.json: {e}")
            print("Creating a default configuration")
            self.createDefaultConfig()
            self.config.jsonConfig.from_json("config.json", required=True)

        # Configuration values
        configMode: int = int(self.tryGetConfig("APP_MODE", required=True))
        telegramMode = configMode in [3, 4]
        obsidianMode = configMode in [1, 4]

        jsonPath = self.tryGetConfig("JSON_PATH", required=True)

        token = self.tryGetConfig("TELEGRAM_BOT_TOKEN", telegramMode, default="NULL_TOKEN")
        chatId = self.tryGetConfig("TELEGRAM_CHAT_ID", telegramMode, default="0")

        appdata = self.tryGetConfig("APPDATA", obsidianMode, default="NULL_APPDATA")
        vaultPath = self.tryGetConfig("OBSIDIAN_VAULT_PATH", obsidianMode, default="NULL_VAULT_PATH")

        dedicationTime = TimeAmount(self.tryGetConfig("DEDICATION_TIME", required=False, default="2p"))
        categoriesConfigOption = self.config.jsonConfig.categories()
        self.container.categories = list[dict](categoriesConfigOption)

        taskDiscoveryPolicies = {
            "context_missing_policy": self.tryGetConfig("CONTEXT_MISSING_POLICY", obsidianMode, default="0"),
            "date_missing_policy": self.tryGetConfig("DATE_MISSING_POLICY", obsidianMode, default="0"),
            "default_context": self.tryGetConfig("DEFAULT_CONTEXT", obsidianMode, default="inbox"),
            "categories_prefixes": [category["prefix"] for category in self.container.categories],
        }

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
            self.container.taskJsonProvider = providers.Singleton(ObsidianVaultTaskJsonProvider, self.container.fileBroker, taskDiscoveryPolicies)
            self.container.taskProvider = providers.Singleton(ObsidianTaskProvider, self.container.taskJsonProvider, self.container.fileBroker)
        else:
            self.container.taskJsonProvider = providers.Singleton(TaskJsonProvider, self.container.fileBroker)
            self.container.taskProvider = providers.Singleton(TaskProvider, self.container.taskJsonProvider, self.container.fileBroker)
        # Heuristics
        self.container.remainingEffortHeuristic = providers.Factory(RemainingEffortHeuristic, dedicationTime)
        self.container.daysToThresholdHeuristic = providers.Factory(DaysToThresholdHeuristic, dedicationTime)
        self.container.slackHeuristic = providers.Factory(SlackHeuristic, dedicationTime)
        self.container.tomorrowSlackHeuristic = providers.Factory(SlackHeuristic, dedicationTime, 1)

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
        self.container.heristicScheduling = providers.Singleton(HeuristicScheduling, dedicationTime)

        # Statistics service
        self.container.statisticsService = providers.Singleton(StatisticsService, self.container.fileBroker, self.container.workLoadAbleFilter, self.container.remainingEffortHeuristic(1.0), self.container.slackHeuristic)

        # Task Manager
        self.container.taskListManager = providers.Singleton(TelegramTaskListManager, self.container.taskProvider().getTaskList(), self.container.heuristicList, self.container.filterList, self.container.statisticsService)

        # Project Manager
        if obsidianMode:
            self.container.projectManager = providers.Singleton(ObsidianProjectManager, self.container.taskProvider, self.container.fileBroker)
        else:
            self.container.projectManager = providers.Singleton(JsonProjectManager, self.container.taskJsonProvider)

        # Reporting service
        self.container.telegramReportingService = providers.Singleton(TelegramReportingService, self.container.userCommService(), self.container.taskProvider(), self.container.heristicScheduling(), self.container.statisticsService(), self.container.taskListManager(), self.container.categories, self.container.projectManager, chatId)
