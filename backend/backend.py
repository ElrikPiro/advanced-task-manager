from os import getenv

from src.containers.TelegramReportingServiceContainer import TelegramReportingServiceContainer

if __name__ == '__main__':

    container = TelegramReportingServiceContainer()

    service = container.container.telegramReportingService()
    service.listenForEvents()