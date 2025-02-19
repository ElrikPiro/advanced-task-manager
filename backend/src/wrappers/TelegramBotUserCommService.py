import telegram

from src.wrappers.interfaces.IUserCommService import IUserCommService
from src.Interfaces.IFileBroker import IFileBroker, FileRegistry


class TelegramBotUserCommService(IUserCommService):
    def __init__(self, bot: telegram.Bot, fileBroker: IFileBroker):
        self.bot: telegram.Bot = bot
        self.fileBroker: IFileBroker = fileBroker
        self.offset = None
        pass

    async def initialize(self) -> None:
        await self.bot.initialize()
        pass

    async def shutdown(self) -> None:
        await self.bot.shutdown()
        pass

    async def sendMessage(self, chat_id: int, text: str, parse_mode: str = None) -> None:
        await self.bot.send_message(chat_id, text, parse_mode=parse_mode)
        pass

    async def getMessageUpdates(self) -> tuple[int, str]:
        result = await self.bot.getUpdates(limit=1, timeout=1, allowed_updates=['message'], offset=self.offset)
        if len(result) == 0:
            return None
        elif result[0].message.text is not None:
            self.offset = result[0].update_id + 1
            return (result[0].message.chat.id, result[0].message.text)
        elif result[0].message.document is not None:
            self.offset = result[0].update_id + 1
            file_id = result[0].message.document.file_id
            file = await self.bot.get_file(file_id)
            fileContent = await file.download_as_bytearray()
            self.fileBroker.writeFileContent(FileRegistry.LAST_RECEIVED_FILE, fileContent.decode())
            detectedFileType = "json"
            return (result[0].message.chat.id, f"/import {detectedFileType}")
        else:
            self.offset = result[0].update_id + 1
            return None

    async def sendFile(self, chat_id: int, data: bytearray) -> None:
        import io
        f = io.BufferedReader(io.BytesIO(data))

        await self.bot.send_document(chat_id, f, filename="export.txt")
