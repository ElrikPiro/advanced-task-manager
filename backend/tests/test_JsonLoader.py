import unittest
from src.JsonLoader import JsonLoader

class JsonLoaderTests(unittest.TestCase):
    def setUp(self):
        self.loader = JsonLoader()
        # Create a valid JSON file
        with open("data.json", "w") as file:
            file.write('{"key": "value"}')

        # Create an invalid JSON file
        with open("invalid.json", "w") as file:
            file.write("invalid")

    def test_load_json(self):
        # Test loading a valid JSON file
        data = self.loader.load_json("data.json")
        self.assertIsNotNone(data)
        self.assertIsInstance(data, dict)

    def test_load_json_invalid_file(self):
        # Test loading an invalid JSON file
        with self.assertRaises(ValueError):
            self.loader.load_json("invalid.json")

    def test_load_json_nonexistent_file(self):
        # Test loading a nonexistent JSON file
        with self.assertRaises(FileNotFoundError):
            self.loader.load_json("nonexistent.json")

if __name__ == '__main__':
    unittest.main()