import unittest
from unittest.mock import Mock, patch
from src.taskjsonproviders.ObsidianDataviewTaskJsonProvider import ObsidianDataviewTaskJsonProvider
from src.Interfaces.IJsonLoader import IJsonLoader

class TestObsidianDataviewTaskJsonProvider(unittest.TestCase):

    def setUp(self):
        self.jsonLoader = Mock(spec=IJsonLoader)
        self.provider = ObsidianDataviewTaskJsonProvider(self.jsonLoader)

    @patch('os.getenv')
    def test_getJson(self, mock_getenv):
        mock_getenv.return_value = '/mock/path'
        self.jsonLoader.load_json.return_value = '{"mock": "json"}'

        result = self.provider.getJson()

        self.jsonLoader.load_json.assert_called_once_with('/mock/path/obsidian/tareas.json')
        self.assertEqual(result, '{"mock": "json"}')

if __name__ == '__main__':
    unittest.main()