import unittest
from unittest.mock import Mock
from src.wrappers.ShellUserCommService import ShellUserCommService
from src.wrappers.Messaging import IAgent


class TestShellUserCommService(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.chat_id = 12345
        self.agent = Mock(spec=IAgent)
        self.service = ShellUserCommService(self.chat_id, self.agent)


if __name__ == '__main__':
    unittest.main()
