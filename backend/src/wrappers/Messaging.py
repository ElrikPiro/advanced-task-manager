from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List

from src.Interfaces.ITaskModel import ITaskModel
from ..Utils import AgendaContent, FilterEntry, TaskInformation, TaskListContent, WorkloadStats


class RenderMode:
    TASK_LIST = 1
    RAW_TEXT = 2
    LIST_UPDATED = 3
    HEURISTIC_LIST = 4
    ALGORITHM_LIST = 5
    FILTER_LIST = 6
    TASK_STATS = 7
    TASK_AGENDA = 8
    TASK_INFORMATION = 9


@dataclass
class MessageContent:
    renderMode: int | None = None
    text: str | None = None
    textList: list[str] | None = None
    filterListDict: List[FilterEntry] | None = None
    taskListContent: TaskListContent | None = None
    task: ITaskModel | None = None
    anonObjectList: List[Dict[str, str]] | None = None
    workloadStats: WorkloadStats | None = None
    agendaContent: AgendaContent | None = None
    taskInformation: TaskInformation | None = None


class IAgent(ABC):
    @property
    @abstractmethod
    def id(self) -> str:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass


class UserAgent(IAgent):
    def __init__(self, id: str, name: str = "user", description: str = "User agent for interacting with the system"):
        self._id = id
        self._name = name
        self._description = description

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description


class BotAgent(IAgent):
    def __init__(self, id: str, name: str, description: str):
        self._id = id
        self._name = name
        self._description = description

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description


class IMessage(ABC):

    @property
    @abstractmethod
    def source(self) -> IAgent:
        pass

    @property
    @abstractmethod
    def destination(self) -> IAgent:
        pass

    @property
    @abstractmethod
    def content(self) -> MessageContent:
        pass

    @property
    @abstractmethod
    def type(self) -> str:
        pass


class InboundMessage(IMessage):
    def __init__(self, source: IAgent, destination: IAgent, command: str, args: list[str]):
        self._source = source
        self._destination = destination
        self._content = MessageContent(text=command, textList=args)

    @property
    def source(self) -> IAgent:
        return self._source

    @property
    def destination(self) -> IAgent:
        return self._destination

    @property
    def content(self) -> MessageContent:
        return self._content

    @property
    def type(self) -> str:
        return "InboundMessage"


class OutboundMessage(IMessage):
    def __init__(self, source: IAgent, destination: IAgent, content: MessageContent, render_mode: int):
        self._source = source
        self._destination = destination
        self._content = content
        content.renderMode = render_mode

    @property
    def source(self) -> IAgent:
        return self._source

    @property
    def destination(self) -> IAgent:
        return self._destination

    @property
    def content(self) -> MessageContent:
        return self._content

    @property
    def type(self) -> str:
        return "OutboundMessage"


class InternalMessage(IMessage):
    def __init__(self, source: IAgent, destination: IAgent, content: MessageContent) -> None:
        self._source = source
        self._destination = destination
        self._content = content

    @property
    def source(self) -> IAgent:
        return self._source

    @property
    def destination(self) -> IAgent:
        return self._destination

    @property
    def content(self) -> MessageContent:
        return self._content

    @property
    def type(self) -> str:
        return "InternalMessage"


class IMessageBuilder(ABC):
    @abstractmethod
    def createInboundMessage(self, source: IAgent, destination: IAgent, command: str, args: list[str]) -> InboundMessage:
        pass

    @abstractmethod
    def createOutboundMessage(self, source: IAgent, destination: IAgent, content: MessageContent, render_mode: int) -> OutboundMessage:
        pass

    @abstractmethod
    def createInternalMessage(self, source: IAgent, destination: IAgent, content: MessageContent) -> InternalMessage:
        pass


class MessageBuilder(IMessageBuilder):
    def createInboundMessage(self, source: IAgent, destination: IAgent, command: str, args: list[str]) -> InboundMessage:
        return InboundMessage(source, destination, command, args)

    def createOutboundMessage(self, source: IAgent, destination: IAgent, content: MessageContent, render_mode: int) -> OutboundMessage:
        return OutboundMessage(source, destination, content, render_mode)

    def createInternalMessage(self, source: IAgent, destination: IAgent, content: MessageContent) -> InternalMessage:
        return InternalMessage(source, destination, content)


class IAgentBuilder(ABC):
    @abstractmethod
    def createUserAgent(self, id: str) -> UserAgent:
        pass

    @abstractmethod
    def createBotAgent(self, id: str, name: str, description: str) -> BotAgent:
        pass
