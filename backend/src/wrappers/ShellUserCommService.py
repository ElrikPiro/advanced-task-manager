from src.wrappers.interfaces.IUserCommService import IUserCommService


class ShellUserCommService(IUserCommService):
    def __init__(self, chatId: int):
        self.offset = 0
        self.chatId = int(chatId)

    async def initialize(self) -> None:
        print("ShellUserBotService initialized")

    async def shutdown(self) -> None:
        print("ShellUserBotService shutdown")

    async def sendMessage(self, chat_id: int, text: str, parse_mode: str = None) -> None:
        print(f"[bot -> {chat_id}]: {text}")

    async def getMessageUpdates(self) -> tuple[int, str]:
        text = input(f"[User({self.chatId})]: ")
        self.offset += 1
        return (self.chatId, text)

    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        print(f"[bot -> {chat_id}]: File sent")
        # show the first 128 bytes of the file with a decoration that indicates the file size
        print(f"File content: {data[:128]}... ({len(data)} bytes)")
