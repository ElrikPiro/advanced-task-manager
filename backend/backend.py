from os import getenv, _exit

from src.containers.TelegramReportingServiceContainer import TelegramReportingServiceContainer

if __name__ == '__main__':

    container = TelegramReportingServiceContainer()

    service = container.container.telegramReportingService()
    service.listenForEvents()
    print("Exiting the program")
    _exit(0) #TODO: fix hanging threads and remove this line
    
    