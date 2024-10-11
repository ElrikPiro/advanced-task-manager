import datetime
import json

from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.IFileBroker import IFileBroker, FileRegistry

class StatisticsService(IStatisticsService):

    def __init__(self, fileBroker : IFileBroker):
        self.workDone : dict[str, float] = {datetime.date.today().isoformat() : 0.0}
        self.fileBroker = fileBroker

    def initialize(self):
        try:
            data = self.fileBroker.readFileContentJson(FileRegistry.STATISTICS_JSON)
            self.workDone = data
        except Exception as e:
            print(f"{e.__class__.__name__}: {e}")
            print("Initializing StatisticsService with empty data.")

    def doWork(self, date : datetime.date, work_units : float):
        self.workDone[date.isoformat()] = self.workDone.get(date.isoformat(), 0.0) + work_units
        # Save to file
        # TODO: use filebroker
        with open(self.jsonPath, 'w', encoding='utf-8') as file:
            json.dump(self.workDone, file)

    def getWorkDone(self, date : datetime.date) -> float:
        return self.workDone.get(date.isoformat(), 0.0)