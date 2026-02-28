from abc import ABC, abstractmethod

class BaseConnector(ABC):
    def __init__(self, name: str, config):
        self.name = name
        self.config = config

    @abstractmethod
    def poll_and_reply(self):
        """
        Poll for new messages from the external chat service and reply to them.
        This method will be called periodically by the kage cron (scheduler).
        """
        pass

    @abstractmethod
    def send_message(self, text: str):
        """
        Send a notification message to the external chat service.
        """
        pass
