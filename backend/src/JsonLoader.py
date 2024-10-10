import os
from .Interfaces.IJsonLoader import IJsonLoader
import json

class JsonLoader(IJsonLoader):
    def __init__(self):
        pass

    def load_json(self, jsonStr : str) -> dict:
        try:
            return json.load(jsonStr)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON in file: {os.linesep}")
            raise e