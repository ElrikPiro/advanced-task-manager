import datetime
import json

from .Interfaces.IStatisticsService import IStatisticsService
from .Interfaces.IJsonLoader import IJsonLoader

class StatisticsService(IStatisticsService):

    def __init__(self, jsonLoader : IJsonLoader, jsonPath : str):
        self.workDone : dict[str, float] = {datetime.date.today().isoformat() : 0.0}
        self.jsonLoader = jsonLoader
        self.jsonPath = jsonPath
        pass

    def initialize(self):
        try:
            data = self.jsonLoader.load_json(self.jsonPath)
            self.workDone = data
        except FileNotFoundError:
            print(f"File '{self.jsonPath}' not found. Initializing with empty data.")
        except ValueError:
            print(f"Error decoding JSON in file '{self.jsonPath}'. Initializing with empty data.")
        pass

    def doWork(self, date : datetime.date, work_units : float):
        self.workDone[date.isoformat()] = self.workDone.get(date.isoformat(), 0.0) + work_units
        # Save to file
        with open(self.jsonPath, 'w', encoding='utf-8') as file:
            json.dump(self.workDone, file)
        pass

    def getWorkDone(self, date : datetime.date) -> float:
        return self.workDone.get(date.isoformat(), 0.0)