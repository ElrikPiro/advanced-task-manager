from abc import ABC, abstractmethod


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
    def __init__(self, id: str):
        self._id = id
        self._name = "user"
        self._description = "User agent for interacting with the system"

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
    def content(self) -> dict:
        pass

    @property
    @abstractmethod
    def type(self) -> str:
        pass


class InboundMessage(IMessage):
    def __init__(self, source: IAgent, destination: IAgent, command: str, args: list[str]):
        self._source = source
        self._destination = destination
        self._content = {
            "command": command,
            "args": args
        }

    @property
    def source(self) -> IAgent:
        return self._source

    @property
    def destination(self) -> IAgent:
        return self._destination

    @property
    def content(self) -> dict:
        if self._content is None:
            raise ValueError("Content must contain 'command' and 'args'")
        return self._content

    @property
    def type(self) -> str:
        return "InboundMessage"


# enum for message render modes
class RenderMode:
    TASK_LIST = 0
    RAW_TEXT = 1
    LIST_UPDATED = 2
    HEURISTIC_LIST = 3
    ALGORITHM_LIST = 4
    FILTER_LIST = 5
    TASK_STATS = 6
    TASK_AGENDA = 7
    TASK_INFORMATION = 8


class OutboundMessage(IMessage):
    def __init__(self, source: IAgent, destination: IAgent, content: dict, render_mode: RenderMode):
        self._source = source
        self._destination = destination
        self._content = content
        self._content['render_mode'] = render_mode

    @property
    def source(self) -> IAgent:
        return self._source

    @property
    def destination(self) -> IAgent:
        return self._destination

    @property
    def content(self) -> dict:
        return self._content

    @property
    def type(self) -> str:
        return "OutboundMessage"


class InternalMessage(IMessage):
    def __init__(self, source: IAgent, destination: IAgent, content: dict):
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
    def content(self) -> dict:
        return self._content

    @property
    def type(self) -> str:
        return "InternalMessage"


class IMessageBuilder(ABC):
    @abstractmethod
    def createInboundMessage(self, source: IAgent, destination: IAgent, command: str, args: list[str]) -> InboundMessage:
        pass

    @abstractmethod
    def createOutboundMessage(self, source: IAgent, destination: IAgent, content: dict, render_mode: RenderMode) -> OutboundMessage:
        pass

    @abstractmethod
    def createInternalMessage(self, source: IAgent, destination: IAgent, content: dict) -> InternalMessage:
        pass


class MessageBuilder(IMessageBuilder):
    def createInboundMessage(self, source: IAgent, destination: IAgent, command: str, args: list[str]) -> InboundMessage:
        return InboundMessage(source, destination, command, args)

    def createOutboundMessage(self, source: IAgent, destination: IAgent, content: dict, render_mode: RenderMode) -> OutboundMessage:
        return OutboundMessage(source, destination, content, render_mode)

    def createInternalMessage(self, source: IAgent, destination: IAgent, content: dict) -> InternalMessage:
        return InternalMessage(source, destination, content)


class IAgentBuilder(ABC):
    @abstractmethod
    def createUserAgent(self, id: str) -> UserAgent:
        pass

    @abstractmethod
    def createBotAgent(self, id: str, name: str, description: str) -> BotAgent:
        pass
