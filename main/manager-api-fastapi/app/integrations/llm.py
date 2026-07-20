from __future__ import annotations

from typing import Any

import httpx

SUMMARY_PROMPT = """你是一个经验丰富的记忆总结者，擅长将对话内容进行总结摘要，遵循以下规则：
1、总结用户的重要信息，以便在未来的对话中提供更个性化的服务
2、不要重复总结，不要遗忘之前记忆，除非原来的记忆超过了1800字，否则不要遗忘、不要压缩用户的历史记忆
3、用户操控的设备音量、播放音乐、天气、退出、不想对话等和用户本身无关的内容，这些信息不需要加入到总结中
4、聊天内容中的今天的日期时间、今天的天气情况与用户事件无关的数据，这些信息如果当成记忆存储会影响后续对话，这些信息不需要加入到总结中
5、不要把设备操控的成果结果和失败结果加入到总结中，也不要把用户的一些废话加入到总结中
6、不要为了总结而总结，如果用户的聊天没有意义，请返回原来的历史记录也是可以的
7、只需要返回总结摘要，严格控制在1800字内
8、不要包含代码、xml，不需要解释、注释和说明，保存记忆时仅从对话提取信息，不要混入示例内容
9、如果提供了历史记忆，请将新对话内容与历史记忆进行智能合并，保留有价值的历史信息，同时添加新的重要信息

历史记忆：
{history_memory}

新对话内容：
{conversation}"""
TITLE_PROMPT = (
    "请根据以下对话内容，生成一个简洁的会话标题（约15字以内），只返回标题，不要包含任何解释或标点符号：\n{conversation}"
)


def _apply_thinking_policy(base_url: str, request: dict[str, Any]) -> None:
    if "aliyuncs.com" in base_url:
        request["enable_thinking"] = False
    elif any(domain in base_url for domain in ("bigmodel.cn", "moonshot.cn", "volces.com")):
        request["thinking"] = {"type": "disabled"}


async def openai_completion(
    config: dict[str, Any],
    prompt: str,
    *,
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> str | None:
    base_url = str(config.get("base_url") or "")
    api_key = str(config.get("api_key") or "")
    if not base_url.strip() or not api_key.strip():
        return None
    api_url = base_url if base_url.endswith("/chat/completions") else f"{base_url.rstrip('/')}/chat/completions"
    request: dict[str, Any] = {
        "model": config.get("model_name") or "gpt-3.5-turbo",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    _apply_thinking_policy(base_url, request)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            api_url,
            json=request,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    return str(content) if content is not None else None
