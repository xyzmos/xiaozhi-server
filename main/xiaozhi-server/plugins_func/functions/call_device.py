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
        "description": (
            "用于设备之间建立语音通话连接。"
            "当用户说出以下意图时调用此工具：\n"
            "1. 主动呼叫：用户说”呼叫XX/打电话给XX/连线XX/打给XX/帮我呼叫XX”时调用，nickname取XX。"
            "例如：”呼叫张三”→nickname=”张三”、”帮我连线小陈”→nickname=”小陈”；\n"
            "2. 接听来电：系统刚提示”您收到来自XX的来电，是否接听？”后，用户说”接听/接通/同意接听/同意连线/同意对话”时调用，"
            "nickname取提示中的XX。\n"
            "如果用户输入不是明确接听，也不是明确拒绝，不得调用call_device，必须先追问一次"
        ),
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