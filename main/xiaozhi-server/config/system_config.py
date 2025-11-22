import uuid

import yaml
import os
from copy import deepcopy

from config.manage_api_client import init_service, get_server_config


def deep_update(original: dict, updates: dict) -> dict:
    """
    递归合并字典，用户配置覆盖默认配置。
    """
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(original.get(key), dict):
            original[key] = deep_update(original.get(key, {}), value)
        else:
            original[key] = deepcopy(value)
    return original


class ConfigNode:
    """递归包装 dict，使其支持点号访问"""

    def __init__(self, data):
        for k, v in data.items():
            if isinstance(v, dict):
                setattr(self, k, ConfigNode(v))
            else:
                setattr(self, k, v)

    def __getitem__(self, item):
        return getattr(self, item, None)

    def __getattr__(self, item):
        # 如果不存在的 key，返回 None 而不是报错
        return None

    def as_dict(self):
        result = {}
        for k, v in self.__dict__.items():
            if isinstance(v, ConfigNode):
                result[k] = v.as_dict()
            else:
                result[k] = v
        return result


class SystemConfig:
    """
    全局配置类（单例，默认路径 + 点号访问 + get 默认值）
    """
    _instance = None
    _config_node = None
    _config_dict = {}

    _DEFAULT_PATH = "config.yaml"  # 默认配置文件路径

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(SystemConfig, cls).__new__(cls)
        return cls._instance

    def __init__(self, user_path: str = 'data/.config.yaml'):
        if self._config_node is None:  # 只初始化一次
            self._load_configs(user_path)

    def _load_configs(self, user_path: str = None):
        # 加载默认配置
        config = self._get_config_from_file(self._DEFAULT_PATH)

        # 约定API配置优先级高于用户本地文件配置
        if config.get("manager-api", {}).get("url"):
            # 配置了API配置则读取API配置
            config = self._get_config_from_api(config)
        else:
            # 否则读取用户本地文件自定义配置
            if user_path:
                user_config = self._get_config_from_file(user_path)
                config = deep_update(config, user_config)

        auth_key = config.get("manager-api", {}).get("secret", "")
        if not auth_key or len(auth_key) == 0 or "你" in auth_key:
            auth_key = str(uuid.uuid4().hex)
        config["server"]["auth_key"] = auth_key

        mcp_endpoint = config.get("mcp_endpoint", None)
        if mcp_endpoint is not None and "你" not in mcp_endpoint:
            # 校验MCP接入点格式
            if validate_mcp_endpoint(mcp_endpoint):
                logger.bind(tag=TAG).info("mcp接入点是\t{}", mcp_endpoint)
                # 将mcp计入点地址转成调用点
                mcp_endpoint = mcp_endpoint.replace("/mcp/", "/call/")
                config["mcp_endpoint"] = mcp_endpoint
            else:
                logger.bind(tag=TAG).error("mcp接入点不符合规范")
                config["mcp_endpoint"] = "你的接入点 websocket地址"

        self._config_dict = config
        self._config_node = ConfigNode(config)

    def __getattr__(self, item):
        # 代理给 ConfigNode
        return getattr(self._config_node, item)

    def as_dict(self):
        """
        转为Dict类型，兼容措施
        """
        return self._config_node.as_dict()

    def get(self, key: str, default=None):
        """
        支持点号路径访问配置，带默认值
        """
        parts = key.split(".")
        current = self._config_dict
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return default
        return current

    @classmethod
    def _get_config_from_file(cls, config_file_path: str = None):
        """从本地文件获取配置"""
        if os.path.exists(config_file_path):
            with open(config_file_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        else:
            raise FileNotFoundError(
                f"找不到{config_file_path}文件，请按教程确认该配置文件是否存在"
            )

    @classmethod
    def _get_config_from_api(cls, config):
        """从Java API获取配置"""
        # 初始化API客户端
        init_service(config)

        # 获取服务器配置
        config_data = get_server_config()
        if config_data is None:
            raise Exception("Failed to fetch server config from API")

        config_data["read_config_from_api"] = True
        config_data["manager-api"] = {
            "url": config["manager-api"].get("url", ""),
            "secret": config["manager-api"].get("secret", ""),
        }
        # server的配置以本地为准
        if config.get("server"):
            config_data["server"] = {
                "ip": config["server"].get("ip", ""),
                "port": config["server"].get("port", ""),
                "http_port": config["server"].get("http_port", ""),
                "vision_explain": config["server"].get("vision_explain", ""),
                "auth_key": config["server"].get("auth_key", ""),
            }
        return config_data
