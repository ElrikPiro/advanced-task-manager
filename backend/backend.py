from os import getenv, _exit

from src.containers.TelegramReportingServiceContainer import TelegramReportingServiceContainer

if __name__ == '__main__':

    container = TelegramReportingServiceContainer()

    service = container.container.telegramReportingService()
    service.listenForEvents()
    print("Exiting the program")
    service.dispose()
    exit(0)
    
    