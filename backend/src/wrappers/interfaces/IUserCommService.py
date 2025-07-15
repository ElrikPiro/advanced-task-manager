from abc import ABC, abstractmethod


class IUserCommService(ABC):

    @abstractmethod
    async def initialize(self) -> None:
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        pass

    @abstractmethod
    async def sendMessage_legacy(self, chat_id: int, text: str) -> None:
        pass

    @abstractmethod
    async def getMessageUpdates_legacy(self) -> tuple[int, str]:
        pass

    @abstractmethod
    async def sendFile_legacy(self, chat_id: int, data: bytearray) -> None:
        pass

    @abstractmethod
    async def sendMessage(self, message: IMessage) -> None:
        pass
