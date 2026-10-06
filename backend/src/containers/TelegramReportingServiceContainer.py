import json
import getpass
import os
import sys
from dependency_injector import containers, providers
import telegram
import typing

from src.Utils import TaskDiscoveryPolicies
from src.wrappers.Messaging import BotAgent, IAgent, MessageBuilder, UserAgent
from src.wrappers.TimeManagement import TimeAmount
from src.taskjsonproviders.ObsidianVaultTaskJsonProvider import ObsidianVaultTaskJsonProvider
from src.TelegramTaskListManager import TelegramTaskListManager
from src.wrappers.TelegramBotUserCommService import TelegramBotUserCommService
from src.wrappers.ShellUserCommService import ShellUserCommService
from src.wrappers.HttpUserCommService import HttpUserCommService
from src.taskproviders.TaskProvider import TaskProvider
from src.taskjsonproviders.TaskJsonProvider import TaskJsonProvider
from src.HeuristicScheduling import HeuristicScheduling
from src.filters.ActiveTaskFilter import ActiveTaskFilter
from src.TelegramReportingService import TelegramReportingService
from src.domain.TaskApplicationService import TaskApplicationService
from src.taskproviders.ObsidianTaskProvider import ObsidianTaskProvider
from src.heuristics.SlackHeuristic import SlackHeuristic
from src.heuristics.RemainingEffortHeuristic import RemainingEffortHeuristic
from src.filters.ContextPrefixTaskFilter import ContextPrefixTaskFilter
from src.filters.ActiveTaskFilter import InactiveTaskFilter
from src.heuristics.DaysToThresholdHeuristic import DaysToThresholdHeuristic
from src.StatisticsService import StatisticsService
from src.FileBroker import FileBroker
from src.AtomicFileStore import AtomicFileStore
from src.NotificationHistoryStore import NotificationHistoryStore
from src.MutationCoordinator import MutationCoordinator
from src.filters.WorkloadAbleFilter import WorkloadAbleFilter
from src.ProjectManager import ObsidianProjectManager
from src.JsonProjectManager import JsonProjectManager
from src.algorithms.GtdAlgorithm import GtdAlgorithm
from src.algorithms.EdfAlgorithm import EdfAlgorithm
from src.algorithms.ShortestJobAlgorithm import ShortestJobAlgorithm
from src.heuristics.StartTimeHeuristic import StartTimeHeuristic
from src.heuristics.CfdHeuristic import CfdHeuristic
from src.heuristics.WorkloadHeuristic import WorkloadHeuristic
from src.wrappers.StreamLogger import StreamLogger


class TelegramReportingServiceContainer():

    # tries to get a configuration value from the environment, if not present
    # then it will try to get it from the json configuration file
    @typing.no_type_check
    def tryGetConfig(self, key: str, required: bool = False, default: str | None = None) -> str | None:
        self.config.query.from_env(key, as_=str, required=False, default=None)
        value = None if self.config.query() == "None" else self.config.query()
        if value is None:
            value = self.config.jsonConfig[key]()
        if value is None and required:
            raise ValueError(f"Configuration value {key} is required")
        elif value is None:
            return default
        return value

    @typing.no_type_check
    def createDefaultConfig(self) -> None:
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
            ]
        }

        # ask the user for an app mode
        appMode = None
        while appMode not in ["1", "2", "3", "4", "5", "6"]:
            print("Please select an app mode:")
            print("\t1 - Obsidian (cmd)")
            print("\t2 - JSON file (cmd)")
            print("\t3 - JSON file (telegram)")
            print("\t4 - Obsidian (telegram)")
            print("\t5 - JSON file (HTTP)")
            print("\t6 - Obsidian (HTTP)")
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

        if appMode in ["5", "6"]:
            # ask the user for HTTP configuration
            httpUrl = input("Please enter the HTTP server URL (default: 0.0.0.0): ") or "0.0.0.0"
            defaultConfig["HTTP_URL"] = httpUrl

            httpPort = input("Please enter the HTTP server port (default: 8080): ") or "8080"
            defaultConfig["HTTP_PORT"] = httpPort

            httpToken = getpass.getpass("Please enter the HTTP authentication token: ")
            defaultConfig["HTTP_TOKEN"] = httpToken

            httpApiPrefix = input("Please enter the HTTP API prefix (default: /api/v1): ") or "/api/v1"
            defaultConfig["HTTP_API_PREFIX"] = httpApiPrefix

            tlsCertChainPath = input("Please enter the TLS certificate chain PEM path: ")
            defaultConfig["HTTP_TLS_CERT_CHAIN_PATH"] = tlsCertChainPath

            tlsPrivateKeyPath = input("Please enter the TLS private key PEM path: ")
            defaultConfig["HTTP_TLS_PRIVATE_KEY_PATH"] = tlsPrivateKeyPath

            httpChatId = input("Please enter the HTTP chat ID (default: 1): ") or "1"
            defaultConfig["HTTP_CHAT_ID"] = httpChatId

        # if os not windows
        if os.name != "nt":
            # we keeping this for legacy reasons
            defaultConfig["APPDATA"] = jsonPath

        if appMode in ["1", "4", "6"]:
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
                    print("Invalid context; select a configured category")
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
            except Exception:
                print("Invalid duration value; try again")
                validPomodoros = False

        defaultConfig["DEDICATION_TIME"] = f"{pomodorosPerDay.as_pomodoros()}p"

        serialized_config = json.dumps(defaultConfig, indent=4, allow_nan=False).encode("utf-8")

        def validate_config(content: bytes) -> None:
            def reject_non_finite_constant(value: str) -> None:
                raise ValueError(f"Invalid non-finite JSON number: {value}")

            decoded = content.decode("utf-8")
            parsed = json.loads(decoded, parse_constant=reject_non_finite_constant)
            if not isinstance(parsed, dict):
                raise TypeError("Configuration must be a JSON object")

        # Bootstrap configuration uses the same atomic file primitive and
        # shared mutation turn as later application data.
        def write_default_config() -> None:
            AtomicFileStore().write("config.json", serialized_config, validate_config)

        self.container.mutationCoordinator().run_job(write_default_config)

    @typing.no_type_check
    def __init__(self) -> None:
        self.container = containers.DynamicContainer()
        self.container.mutationCoordinator = providers.Object(MutationCoordinator())
        self.config = providers.Configuration()

        # Configuration
        try:
            self.config.jsonConfig.from_json("config.json", required=True)
        except Exception:
            print("Unable to read configuration")
            print("Creating a default configuration")
            self.createDefaultConfig()
            self.config.jsonConfig.from_json("config.json", required=True)

        # Configuration values
        configMode: int = int(self.tryGetConfig("APP_MODE", required=True) or "")
        telegramMode = configMode in [3, 4]
        httpMode = configMode in [5, 6]
        obsidianMode = configMode in [1, 4, 6]

        jsonPath = self.tryGetConfig("JSON_PATH", required=True)

        token = self.tryGetConfig("TELEGRAM_BOT_TOKEN", telegramMode, default="NULL_TOKEN")
        chatId = self.tryGetConfig("TELEGRAM_CHAT_ID", telegramMode, default="0")

        httpUrl = self.tryGetConfig("HTTP_URL", httpMode, default="0.0.0.0")
        httpPort = int(self.tryGetConfig("HTTP_PORT", httpMode, default="8080") or "8080")
        httpToken = self.tryGetConfig("HTTP_TOKEN", httpMode, default="NULL_HTTP_TOKEN")
        httpApiPrefix = self.tryGetConfig("HTTP_API_PREFIX", httpMode, default="/api/v1")
        if httpMode:
            tlsCertChainPath = self.tryGetConfig(
                "HTTP_TLS_CERT_CHAIN_PATH", required=True
            )
            tlsPrivateKeyPath = self.tryGetConfig(
                "HTTP_TLS_PRIVATE_KEY_PATH", required=True
            )
            if not tlsCertChainPath or not tlsCertChainPath.strip():
                raise ValueError("TLS certificate chain path is required")
            if not tlsPrivateKeyPath or not tlsPrivateKeyPath.strip():
                raise ValueError("TLS private key path is required")
        else:
            tlsCertChainPath = None
            tlsPrivateKeyPath = None
        httpChatId = int(self.tryGetConfig("HTTP_CHAT_ID", httpMode, default="1") or "1")

        appdata = self.tryGetConfig("APPDATA", obsidianMode, default="NULL_APPDATA")
        vaultPath = self.tryGetConfig("OBSIDIAN_VAULT_PATH", obsidianMode, default="NULL_VAULT_PATH")

        dedicationTime = TimeAmount(self.tryGetConfig("DEDICATION_TIME", required=False, default="2p"))
        categoriesConfigOption = self.config.jsonConfig.categories()
        self.container.categories = list[dict[str, str]](categoriesConfigOption)

        taskDiscoveryPolicies: TaskDiscoveryPolicies = TaskDiscoveryPolicies(
            context_missing_policy=self.tryGetConfig("CONTEXT_MISSING_POLICY", obsidianMode, default="0"),
            date_missing_policy=self.tryGetConfig("DATE_MISSING_POLICY", obsidianMode, default="0"),
            default_context=self.tryGetConfig("DEFAULT_CONTEXT", required=False, default="inbox"),
            categories_prefixes=[category["prefix"] for category in self.container.categories]
        )

        # External services

        ## Telegram bots
        self.container.bot = providers.Singleton(telegram.Bot, token=token)

        # Data providers
        self.container.fileBroker = providers.Singleton(
            FileBroker,
            jsonPath,
            appdata,
            vaultPath,
            mutation_coordinator=self.container.mutationCoordinator(),
        )
        if httpMode:
            self.container.notificationHistoryStore = providers.Singleton(
                NotificationHistoryStore,
                self.container.fileBroker,
                self.container.mutationCoordinator(),
                httpToken,
            )
        cleanup_directories = [str(jsonPath)]
        if obsidianMode:
            cleanup_directories.extend([os.path.join(str(appdata), "obsidian"), str(vaultPath)])
        self.container.fileBroker().cleanupAtomicTemps(cleanup_directories)

        # User communication services
        botId: IAgent = BotAgent(id="TaskManagerBot", name="Task Manager Bot", description="Bot for managing tasks")

        self.container.shellUserCommService = providers.Singleton(ShellUserCommService, chatId, botId)
        self.container.telegramUserCommService = providers.Singleton(
            TelegramBotUserCommService,
            self.container.bot,
            self.container.fileBroker,
            botId,
            authorized_chat_id=chatId,
        )
        # Select the appropriate user communication service based on mode
        if telegramMode:
            self.container.userCommService = self.container.telegramUserCommService
        elif not httpMode:
            self.container.userCommService = self.container.shellUserCommService

        if obsidianMode:
            self.container.taskJsonProvider = providers.Singleton(
                ObsidianVaultTaskJsonProvider,
                self.container.fileBroker,
                taskDiscoveryPolicies,
                mutation_coordinator=self.container.mutationCoordinator(),
                auto_start=False,
            )
            self.container.taskProvider = providers.Singleton(
                ObsidianTaskProvider,
                self.container.taskJsonProvider,
                self.container.fileBroker,
                mutation_coordinator=self.container.mutationCoordinator(),
            )
        else:
            self.container.taskJsonProvider = providers.Singleton(
                TaskJsonProvider,
                self.container.fileBroker,
                mutation_coordinator=self.container.mutationCoordinator(),
            )
            self.container.taskProvider = providers.Singleton(
                TaskProvider,
                self.container.taskJsonProvider,
                self.container.fileBroker,
                mutation_coordinator=self.container.mutationCoordinator(),
            )
        # Heuristics
        self.container.remainingEffortHeuristic = providers.Factory(RemainingEffortHeuristic, dedicationTime)
        self.container.daysToThresholdHeuristic = providers.Factory(DaysToThresholdHeuristic, dedicationTime)
        self.container.slackHeuristic = providers.Factory(SlackHeuristic, dedicationTime)
        self.container.tomorrowSlackHeuristic = providers.Factory(SlackHeuristic, dedicationTime, 1)
        self.container.cfdHeuristic = providers.Factory(CfdHeuristic, dedicationTime)
        self.container.workloadHeuristic = providers.Factory(WorkloadHeuristic)

        ## Heuristic list
        self.container.heuristicList = providers.List(
            ("Remaining Effort(1)", self.container.remainingEffortHeuristic(1.0)),
            ("Remaining Time(100)", self.container.daysToThresholdHeuristic(100.0)),
            ("Remaining Time(1)", self.container.daysToThresholdHeuristic(1.0)),
            ("Slack Heuristic", self.container.slackHeuristic()),
            ("Start Time Heuristic", StartTimeHeuristic()),
            ("CFD Heuristic", self.container.cfdHeuristic()),
            ("Workload Heuristic", self.container.workloadHeuristic()),
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
            self.container.orderedCategories.append((description, self.container.contextPrefixTaskFilter(prefix=prefix), False))

        self.container.workLoadAbleFilter = providers.Singleton(WorkloadAbleFilter, self.container.activeFilter())

        ## Filter list
        self.container.filterList = [
            ("All active task filter", self.container.activeFilter(), True),
            ("All inactive task filter", InactiveTaskFilter(), False),
        ]
        self.container.filterList.extend(self.container.orderedCategories)

        # Statistics service
        self.container.statisticsService = providers.Singleton(
            StatisticsService,
            self.container.fileBroker,
            self.container.workLoadAbleFilter,
            self.container.remainingEffortHeuristic(1.0),
            self.container.slackHeuristic,
            mutation_coordinator=self.container.mutationCoordinator(),
        )

        # Algorithm list
        self.container.algorithmList = providers.List(
            ("GTD Algorithm", GtdAlgorithm(self.container.orderedCategories, self.container.orderedHeuristics(), self.container.defaultHeuristic(), self.container.statisticsService(), self.container.cfdHeuristic())),
            ("EDF Algorithm", EdfAlgorithm()),
            ("Shortest Job Algorithm", ShortestJobAlgorithm()),
        )

        # Scheduling algorithm
        self.container.heristicScheduling = providers.Singleton(HeuristicScheduling, dedicationTime, self.container.taskProvider)

        # Task Manager
        # The channel view starts empty internally. Markdown task discovery is
        # scheduled only after the listener has initialized and readiness gates
        # prevent this placeholder from being presented as a loaded empty vault.
        self.container.taskListManager = providers.Singleton(TelegramTaskListManager, [], self.container.algorithmList, self.container.heuristicList, self.container.filterList, self.container.statisticsService)

        # Project Manager
        if obsidianMode:
            self.container.projectManager = providers.Singleton(
                ObsidianProjectManager,
                self.container.taskProvider,
                self.container.fileBroker,
                mutation_coordinator=self.container.mutationCoordinator(),
            )
        else:
            self.container.projectManager = providers.Singleton(
                JsonProjectManager,
                self.container.taskJsonProvider,
                mutation_coordinator=self.container.mutationCoordinator(),
            )

        self.container.taskApplicationService = providers.Singleton(
            TaskApplicationService,
            self.container.taskProvider(),
            self.container.heristicScheduling(),
            self.container.statisticsService(),
            self.container.taskListManager(),
            self.container.categories,
            self.container.projectManager(),
            mutation_coordinator=self.container.mutationCoordinator(),
        )

        # Construct the HTTP adapter only after its application service exists.
        # The provider dependency keeps the HTTP listener and operation service
        # as singletons without introducing a back-reference cycle.
        if httpMode:
            self.container.httpUserCommService = providers.Singleton(
                HttpUserCommService,
                httpUrl,
                httpPort,
                httpToken,
                httpChatId,
                botId,
                tls_cert_chain_path=tlsCertChainPath,
                tls_private_key_path=tlsPrivateKeyPath,
                application_service=self.container.taskApplicationService,
                api_prefix=httpApiPrefix,
                notification_history_store=self.container.notificationHistoryStore,
            )
            self.container.userCommService = self.container.httpUserCommService

        # Message builder
        self.container.messageBuilder = providers.Singleton(MessageBuilder)

        # Logger
        self.container.logger = providers.Singleton(StreamLogger, sys.stdout)

        # Reporting service
        user: UserAgent = UserAgent(id=chatId, name="User", description="User Agent for Telegram Reporting Service")
        self.container.telegramReportingService = providers.Singleton(
            TelegramReportingService,
            self.container.userCommService(),
            self.container.taskProvider(),
            self.container.heristicScheduling(),
            self.container.statisticsService(),
            self.container.taskListManager(),
            self.container.categories,
            self.container.projectManager,
            self.container.messageBuilder,
            user,
            self.container.logger,
            self.container.taskApplicationService(),
            mutation_coordinator=self.container.mutationCoordinator(),
        )
