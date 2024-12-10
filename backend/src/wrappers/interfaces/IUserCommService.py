from abc import ABC, abstractmethod

class IUserCommService(ABC):

    @abstractmethod
    async def initialize(self) -> None:
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        pass

    @abstractmethod
    async def sendMessage(self, chat_id: int, text: str) -> None:
        pass

    @abstractmethod
    async def getMessageUpdates(self) -> tuple[int, str]:
        pass

    @abstractmethod
    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        pass