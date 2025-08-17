from abc import ABC, abstractmethod

from ..Messaging import IAgent, IMessage


class IUserCommService(ABC):

    @abstractmethod
    async def initialize(self) -> None:
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        pass

    @abstractmethod
    async def getMessageUpdates(self) -> list[IMessage]:
        pass

    @abstractmethod
    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        pass

    @abstractmethod
    async def sendMessage(self, message: IMessage) -> None:
        pass

    @abstractmethod
    def getBotAgent(self) -> IAgent:
        pass
