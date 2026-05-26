"""呼叫设备工具"""
import httpx
import hashlib
import requests
from datetime import datetime
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
        "description": "主动呼叫其他小智设备进行语音通话。**重要**：只有当用户主动说\"我想跟XX通话\"、\"帮我打电话给XX\"时才调用此工具。当收到\"来自XX的来电\"消息时，不要调用此工具，让设备自然播报即可。",
        "parameters": {
            "type": "object",
            "properties": {
                "nickname": {
                    "type": "string",
                    "description": "目标设备的备注名，例如：小陈、小翁"
                },
                "response_success": {
                    "type": "string",
                    "description": "呼叫成功时的回复"
                },
                "response_failure": {
                    "type": "string",
                    "description": "呼叫失败时的回复"
                }
            },
            "required": ["nickname", "response_success", "response_failure"],
        },
    },
}


def _api_request(url: str, params: dict, headers: dict) -> dict:
    """发送API请求并处理响应"""
    resp = requests.get(url, params=params, headers=headers, timeout=10)
    return resp.json()


def _call_gateway(gateway_url: str, gateway_secret: str, caller_mac: str, target_mac: str, caller_nickname: str) -> dict:
    """呼叫网关"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    token = hashlib.sha256((date_str + gateway_secret).encode()).hexdigest()
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=5.0) as client:
        resp = client.post(
            f"{gateway_url}/api/call/request",
            json={"caller_mac": caller_mac, "target_mac": target_mac, "caller_nickname": caller_nickname},
            headers=headers
        )
        return resp.json()


@register_function("call_device", call_device_function_desc, ToolType.SYSTEM_CTL)
def call_device(conn: "ConnectionHandler", nickname: str, response_success: str = None, response_failure: str = None):
    try:
        caller_mac = conn.headers.get("device-id", "")
        if not caller_mac:
            return ActionResponse(action=Action.RESPONSE, response="无法获取本机MAC地址")

        api_config = conn.config.get("manager-api", {})
        api_url = api_config.get("url", "")
        api_secret = api_config.get("secret", "")
        if not api_url or not api_secret:
            logger.bind(tag=TAG).error("manager-api配置缺失")
            return ActionResponse(action=Action.RESPONSE, response="配置错误，请稍后再试")

        try:
            result = _api_request(
                f"{api_url}/device/address-book/lookup",
                params={"callerMac": caller_mac, "nickname": nickname},
                headers={"Authorization": f"Bearer {api_secret}"}
            )
        except Exception as e:
            logger.bind(tag=TAG).error(f"通讯录查找请求失败: {e}")
            return ActionResponse(action=Action.RESPONSE, response="通讯录查询失败，请稍后再试")

        if result.get("code") != 0:
            return ActionResponse(action=Action.RESPONSE, response=f"未找到备注为'{nickname}'的设备")

        lookup_result = result.get("data")
        if not lookup_result:
            return ActionResponse(action=Action.RESPONSE, response=f"未找到备注为'{nickname}'的设备")

        target_mac = lookup_result.get("targetMac")
        caller_nickname = lookup_result.get("callerNickname")
        has_permission = lookup_result.get("hasPermission", "false") == "true"

        if not target_mac:
            return ActionResponse(action=Action.RESPONSE, response=f"未找到备注为'{nickname}'的设备")

        if not caller_nickname:
            return ActionResponse(action=Action.RESPONSE, response="呼叫失败，您不是对方的联系人")

        if not has_permission:
            return ActionResponse(action=Action.RESPONSE, response="呼叫失败，您没有权限呼叫该设备")

        plugin_config = conn.config.get("plugins", {}).get("call_device", {})
        gateway_url = plugin_config.get("gateway_url", "http://127.0.0.1:8007")
        gateway_secret = plugin_config.get("gateway_secret", "")

        try:
            gw_result = _call_gateway(gateway_url, gateway_secret, caller_mac, target_mac, caller_nickname)
        except httpx.ConnectError:
            logger.bind(tag=TAG).error(f"无法连接到网关: {gateway_url}")
            return ActionResponse(action=Action.RESPONSE, response="无法连接到通话网关，请稍后再试")
        except httpx.TimeoutException:
            logger.bind(tag=TAG).error("网关请求超时")
            return ActionResponse(action=Action.RESPONSE, response="通话请求超时，请稍后再试")

        conn.calling = True
        status = gw_result.get("status")
        if status == "bridged":
            return ActionResponse(action=Action.NONE, result="bridged", response=f"已与{nickname}建立通话")
        elif status == "pending":
            return ActionResponse(action=Action.NONE, result="pending", response=f"正在呼叫{nickname}，请等待对方接听")
        else:
            error_msg = gw_result.get("message", "未知错误")
            return ActionResponse(action=Action.RESPONSE, response=f"呼叫失败：{error_msg}")

    except Exception as e:
        logger.bind(tag=TAG).error(f"call_device错误: {e}")
        return ActionResponse(action=Action.ERROR, response=f"呼叫失败: {str(e)}")
