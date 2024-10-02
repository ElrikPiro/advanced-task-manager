from src.wrappers.interfaces.IUserCommService import IUserCommService

class ShellUserBotService(IUserCommService):
    def __init__(self):
        self.offset = 0

    async def initialize(self) -> None:
        print("ShellUserBotService initialized")

    async def shutdown(self) -> None:
        print("ShellUserBotService shutdown")

    async def sendMessage(self, chat_id: int, text: str, parse_mode : str = None) -> None:
        print(f"[{chat_id}]: {text}")
    
    async def getMessageUpdates(self) -> tuple[int, str]:
        text = input("[User]: ")
        self.offset += 1
        return (self.offset, text)