import threading
from ..config import get_global_config
from .base import BaseConnector
from .discord import DiscordConnector
from .slack import SlackConnector
from ..config import DiscordConnectorConfig, SlackConnectorConfig

def get_connector(name: str) -> BaseConnector | None:
    """
    Get an active connector instance by name.
    """
    config = get_global_config()
    c_dict = config.connectors.get(name)
    if not c_dict:
        return None
        
    c_type = c_dict.get("type", "unknown")
    if c_type == "discord":
        try:
            d_config = DiscordConnectorConfig(**c_dict)
            if d_config.active:
                return DiscordConnector(name, d_config)
        except Exception as e:
            print(f"[kage] Error parsing connector '{name}': {e}")
    elif c_type == "slack":
        try:
            s_config = SlackConnectorConfig(**c_dict)
            if s_config.active:
                return SlackConnector(name, s_config)
        except Exception as e:
            print(f"[kage] Error parsing connector '{name}': {e}")
    
    return None

def run_connectors():
    """
    Run all active connectors concurrently and wait for them to finish polling and replying.
    """
    config = get_global_config()
    active_connectors = []
    
    for name in config.connectors.keys():
        c = get_connector(name)
        if c:
            active_connectors.append(c)
        
    threads = []
    for connector in active_connectors:
        t = threading.Thread(target=connector.poll_and_reply)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
