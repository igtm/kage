import threading
from ..agent import get_current_agent_name
from ..config import get_global_config
from .base import BaseConnector
from .discord import DiscordConnector
from .slack import SlackConnector
from .telegram import TelegramConnector
from ..config import (
    DiscordConnectorConfig,
    SlackConnectorConfig,
    TelegramConnectorConfig,
)


def _agent_filter(config, current_agent: str | None) -> bool:
    """現 agent 配下以外の connector を除外するかどうか。config は未使用だが可視化用。"""
    return current_agent is not None


def _connector_agent_name(config, c_dict: dict) -> str:
    agent_name = c_dict.get("agent")
    if hasattr(agent_name, "unwrap"):
        agent_name = agent_name.unwrap()
    return agent_name or config.default_agent


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


def _filter_for_agent(config, items):
    """現 agent 配下の (name, c_dict) のみに絞る。人間（None）は全件。"""
    current = get_current_agent_name(config)
    if current is None:
        return items
    filtered = []
    for name, c_dict in items:
        bound = _connector_agent_name(config, c_dict)
        if bound == current:
            filtered.append((name, c_dict))
        else:
            print(
                f"[kage] Skipping connector '{name}' (bound to agent '{bound}', "
                f"current agent '{current}')."
            )
    return filtered


def run_connectors():
    """
    Run all connectors with poll=True concurrently and wait for them to finish polling and replying.
    """
    config = get_global_config()
    poll_candidates = [(name, c_dict) for name, c_dict in config.connectors.items()]
    scoped = _filter_for_agent(config, poll_candidates)

    poll_connectors = []
    for name, c_dict in scoped:
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


def run_realtime_connectors():
    """
    Run all connectors with realtime=True concurrently.
    This function blocks until all realtime listeners exit (normally never).
    """
    config = get_global_config()
    realtime_candidates = list(config.connectors.items())
    scoped = _filter_for_agent(config, realtime_candidates)

    realtime_connectors: list[BaseConnector] = []
    for name, c_dict in scoped:
        connector = _build_connector(name, c_dict)
        if connector and connector.config.realtime:
            realtime_connectors.append(connector)

    if not realtime_connectors:
        print("[kage] No connectors have realtime=true. Nothing to start.")
        return

    threads = []
    for connector in realtime_connectors:
        t = threading.Thread(target=connector.realtime, daemon=True)
        threads.append(t)
        t.start()

    try:
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("[kage] Stopping realtime connectors...")
