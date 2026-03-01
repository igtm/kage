import threading
from ..config import get_global_config
from .base import BaseConnector
from .discord import DiscordConnector
from .slack import SlackConnector
from .telegram import TelegramConnector
from ..config import DiscordConnectorConfig, SlackConnectorConfig, TelegramConnectorConfig

def _build_connector(name: str, c_dict: dict) -> BaseConnector | None:
    """
    Build a connector instance from config dict. Returns None if config is invalid.
    """
    c_type = c_dict.get("type", "unknown")
    if c_type == "discord":
        try:
            return DiscordConnector(name, DiscordConnectorConfig(**c_dict))
        except Exception as e:
            print(f"[kage] Error parsing connector '{name}': {e}")
    elif c_type == "slack":
        try:
            return SlackConnector(name, SlackConnectorConfig(**c_dict))
        except Exception as e:
            print(f"[kage] Error parsing connector '{name}': {e}")
    elif c_type == "telegram":
        try:
            return TelegramConnector(name, TelegramConnectorConfig(**c_dict))
        except Exception as e:
            print(f"[kage] Error parsing connector '{name}': {e}")
    return None


def get_connector(name: str) -> BaseConnector | None:
    """
    Get a connector instance by name for sending messages.
    Always returns a valid connector regardless of the poll flag,
    as long as the connector config is valid and has required credentials.
    """
    config = get_global_config()
    c_dict = config.connectors.get(name)
    if not c_dict:
        return None
    return _build_connector(name, c_dict)


def run_connectors():
    """
    Run all connectors with poll=True concurrently and wait for them to finish polling and replying.
    """
    config = get_global_config()
    poll_connectors = []
    
    for name, c_dict in config.connectors.items():
        connector = _build_connector(name, c_dict)
        if connector and connector.config.poll:
            poll_connectors.append(connector)
        
    threads = []
    for connector in poll_connectors:
        t = threading.Thread(target=connector.poll_and_reply)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
