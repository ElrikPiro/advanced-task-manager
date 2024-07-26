from .Interfaces.IJsonLoader import IJsonLoader
import json

class JsonLoader(IJsonLoader):
    def __init__(self):
        pass

    def load_json(self, file_path) -> dict:
        self.file_path = file_path
        try:
            with open(self.file_path, 'r', encoding='utf-8') as file:
                data = json.load(file)
                return data
        except FileNotFoundError:
            print(f"File '{self.file_path}' not found.")
            raise FileNotFoundError
        except json.JSONDecodeError:
            print(f"Error decoding JSON in file '{self.file_path}'.")
            raise ValueError