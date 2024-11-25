import telegram

from src.wrappers.interfaces.IUserCommService import IUserCommService

class TelegramBotUserCommService(IUserCommService):
    def __init__(self, bot : telegram.Bot):
        self.bot : telegram.Bot = bot
        self.offset = None
        pass

    async def initialize(self) -> None:
        await self.bot.initialize()
        pass

    async def shutdown(self) -> None:
        await self.bot.shutdown()
        pass

    async def sendMessage(self, chat_id: int, text: str, parse_mode : str = None) -> None:
        await self.bot.send_message(chat_id, text, parse_mode=parse_mode)
        pass
    
    async def getMessageUpdates(self) -> tuple[int, str]:
        result = await self.bot.getUpdates(limit=1, timeout=1, allowed_updates=['message'], offset=self.offset)
        if len(result) == 0:
            return None
        else:
            self.offset = result[0].update_id + 1
            return (result[0].message.chat.id, result[0].message.text)
        
    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        import io
        from io import BufferedReader as file
        f = io.BufferedReader(io.BytesIO(data))

        await self.bot.send_document(chat_id, f, filename="export.txt")