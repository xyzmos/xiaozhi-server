from config.logger import setup_logging
from core.utils.util import check_model_key
from plugins_func.register import PluginContext

TAG = __name__
logger = setup_logging()


def append_devices_to_prompt(context: PluginContext):
    """添加设备列表到提示词 - 重构版"""
    intent_type = context.get_config('Intent.type')
    if intent_type == "function_call":
        funcs = context.get_config('Intent.function_call.functions', [])

        config_source = (
            "home_assistant"
            if context.get_config("plugins.home_assistant")
            else "hass_get_state"
        )

        if "hass_get_state" in funcs or "hass_set_state" in funcs:
            prompt = "\n下面是我家智能设备列表（位置，设备名，entity_id），可以通过homeassistant控制\n"
            deviceStr = context.get_config(f"plugins.{config_source}.devices", "")

            # 获取session_context并更新系统提示词
            session_context = context.get_context()
            updated_prompt = session_context.get_config('LLM.prompt', '') + prompt + deviceStr + "\n"

            session_context.dialogue.update_system_message(updated_prompt)


def initialize_hass_handler(context: PluginContext):
    """初始化Home Assistant配置 - 重构版"""
    ha_config = {}

    load_function_plugin = context.get_config('load_function_plugin', False)
    if not load_function_plugin:
        return ha_config

    # 确定配置来源
    config_source = (
        "home_assistant"
        if context.get_config("plugins.home_assistant")
        else "hass_get_state"
    )

    plugin_config = context.get_config(f"plugins.{config_source}", {})
    if not plugin_config:
        return ha_config

    # 统一获取配置
    ha_config["base_url"] = plugin_config.get("base_url")
    ha_config["api_key"] = plugin_config.get("api_key")

    # 统一检查API密钥
    model_key_msg = check_model_key("home_assistant", ha_config.get("api_key"))
    if model_key_msg:
        logger.bind(tag=TAG).error(model_key_msg)

    return ha_config
