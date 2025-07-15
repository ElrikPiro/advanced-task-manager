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


class OutboundMessage(IMessage):
    def __init__(self, source: IAgent, destination: IAgent, content: dict, render_mode: RenderMode):
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

#TODO: Abstract message factory to create messages based on type