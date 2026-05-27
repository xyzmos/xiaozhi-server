"""呼叫设备工具"""
import requests
from typing import TYPE_CHECKING

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__
logger = setup_logging()

call_device_function_desc = {
    "type": "function",
    "function": {
        "name": "call_device",
        "description": "主动呼叫其他小智设备进行语音通话。**重要**：只有当用户主动说'我想跟XX通话'、'帮我打电话给XX'时才调用此工具。当收到'来自XX的来电'消息时，不要调用此工具，让设备自然播报即可。",
        "parameters": {
            "type": "object",
            "properties": {
                "nickname": {"type": "string", "description": "目标设备的备注名，例如：小陈、小翁"},
            },
            "required": ["nickname"],
        },
    },
}


def _request_api(url: str, params: dict, headers: dict) -> requests.Response:
    return requests.get(url, params=params, headers=headers, timeout=10)


def _failed_reply(msg: str) -> ActionResponse:
    return ActionResponse(action=Action.RESPONSE, response=msg)


@register_function("call_device", call_device_function_desc, ToolType.SYSTEM_CTL)
def call_device(conn: "ConnectionHandler", nickname: str):
    caller_mac = conn.headers.get("device-id")
    if not caller_mac:
        return _failed_reply("无法获取本机MAC地址")

    api_config = conn.config.get("manager-api", {})
    api_url = api_config.get("url")
    api_secret = api_config.get("secret")
    if not api_url or not api_secret:
        logger.bind(tag=TAG).error("manager-api配置缺失")
        return _failed_reply("配置错误，请稍后再试")

    headers = {"Authorization": f"Bearer {api_secret}"}

    # 查询通讯录
    try:
        resp = _request_api(
            f"{api_url}/device/address-book/lookup",
            params={"callerMac": caller_mac, "nickname": nickname},
            headers=headers,
        )
        result = resp.json()
    except requests.RequestException as e:
        logger.bind(tag=TAG).error(f"通讯录查找请求失败: {e}")
        return _failed_reply("通讯录查询失败，请稍后再试")

    if result.get("code") != 0 or not result.get("data"):
        return _failed_reply(f"未找到备注为'{nickname}'的设备")

    data = result["data"]
    target_mac = data.get("targetMac")
    caller_nickname = data.get("callerNickname")
    has_permission = data.get("hasPermission")

    if not target_mac:
        return _failed_reply(f"未找到备注为'{nickname}'的设备")
    if not caller_nickname:
        return _failed_reply("呼叫失败，您不是对方的联系人")
    if not has_permission:
        return _failed_reply("呼叫失败，您没有权限呼叫该设备")

    # 通过Java中转调用网关
    try:
        resp = _request_api(
            f"{api_url}/device/call/forward",
            params={"callerMac": caller_mac, "targetMac": target_mac, "callerNickname": caller_nickname},
            headers=headers,
        )
        result = resp.json()
    except requests.RequestException as e:
        logger.bind(tag=TAG).error(f"呼叫请求转发失败: {e}")
        return _failed_reply("呼叫失败，请稍后再试")

    if result.get("code") != 0:
        return _failed_reply(result.get("msg", "呼叫失败"))

    call_data = result.get("data", {})
    if call_data.get("status") == "offline":
        return _failed_reply(call_data.get("message"))

    conn.calling = True
    return ActionResponse(action=Action.NONE, response=f"正在呼叫{nickname}，请等待对方接听")