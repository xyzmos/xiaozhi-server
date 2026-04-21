import uuid
import re
from typing import List, Dict
from datetime import datetime


class Message:
    def __init__(
            self,
            role: str,
            content: str = None,
            uniq_id: str = None,
            tool_calls=None,
            tool_call_id=None,
            is_temporary=False,
    ):
        self.uniq_id = uniq_id if uniq_id is not None else str(uuid.uuid4())
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id
        self.is_temporary = is_temporary  # 标记临时消息（如工具调用提醒）


class Dialogue:
    def __init__(self):
        self.dialogue: List[Message] = []
        # 获取当前时间
        self.current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def put(self, message: Message):
        self.dialogue.append(message)

    def getMessages(self, m, dialogue):
        if m.tool_calls is not None:
            dialogue.append({"role": m.role, "tool_calls": m.tool_calls})
        elif m.role == "tool":
            dialogue.append(
                {
                    "role": m.role,
                    "tool_call_id": (
                        str(uuid.uuid4()) if m.tool_call_id is None else m.tool_call_id
                    ),
                    "content": m.content,
                }
            )
        else:
            dialogue.append({"role": m.role, "content": m.content})

    def get_llm_dialogue(self) -> List[Dict[str, str]]:
        # 直接调用get_llm_dialogue_with_memory，传入None作为memory_str
        # 这样确保说话人功能在所有调用路径下都生效
        return self.get_llm_dialogue_with_memory(None, None)

    def update_system_message(self, new_content: str):
        """更新或添加系统消息"""
        # 查找第一个系统消息
        system_msg = next((msg for msg in self.dialogue if msg.role == "system"), None)
        if system_msg:
            system_msg.content = new_content
        else:
            self.put(Message(role="system", content=new_content))

    def trim_history(self, max_turns: int = 10) -> int:
        """
        智能截断对话历史，保留工具调用的完整性

        Args:
            max_turns: 保留的最大对话轮数（每轮 = user + assistant/tool 相关消息）

        Returns:
            int: 被移除的消息数量
        """
        if len(self.dialogue) <= max_turns * 2 + 1:  # +1 是系统消息
            return 0

        # 分离系统消息和对话消息
        system_messages = [msg for msg in self.dialogue if msg.role == "system"]
        conversation_messages = [msg for msg in self.dialogue if msg.role != "system"]

        if len(conversation_messages) <= max_turns * 2:
            return 0

        # 智能截断：保留完整的工具调用链路
        keep_messages = []
        i = len(conversation_messages) - 1
        turn_count = 0

        while i >= 0 and turn_count < max_turns:
            msg = conversation_messages[i]

            # 从后向前收集消息
            if msg.role == "user":
                # 遇到 user 消息，说明一轮对话开始
                keep_messages.insert(0, msg)
                turn_count += 1
                i -= 1
            elif msg.role == "assistant":
                # 收集 assistant 消息
                keep_messages.insert(0, msg)

                # 如果这个 assistant 有 tool_calls，需要收集对应的 tool 响应
                if msg.tool_calls is not None:
                    i -= 1
                    # 继续向后收集所有相关的 tool 消息
                    while i >= 0 and conversation_messages[i].role == "tool":
                        keep_messages.insert(0, conversation_messages[i])
                        i -= 1
                else:
                    i -= 1
            elif msg.role == "tool":
                # tool 消息应该已经被上面的逻辑收集了
                # 如果单独遇到，也要保留（防止边界情况）
                keep_messages.insert(0, msg)
                i -= 1
            else:
                i -= 1

        removed_count = len(conversation_messages) - len(keep_messages)

        # 重建对话列表
        self.dialogue = system_messages + keep_messages

        return removed_count

    def _ensure_tool_calls_complete(self, messages: List[Message]) -> List[Message]:
        """
        确保所有 tool_calls 都有对应的 tool 响应
        修复被打断导致的悬空 tool_calls，防止大模型 API 报 400 错误
        """
        pending_tool_calls = set()
        result = []

        for msg in messages:
            result.append(msg)

            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tc_id:
                        pending_tool_calls.add(tc_id)

            elif msg.role == "tool" and msg.tool_call_id:
                pending_tool_calls.discard(msg.tool_call_id)

        for missing_id in pending_tool_calls:
            dummy_tool_msg = Message(
                role="tool",
                content='{"status": "interrupted", "message": "动作已取消/被打断"}',
                tool_call_id=missing_id
            )
            result.append(dummy_tool_msg)

        return result

    def get_llm_dialogue_with_memory(
            self, memory_str: str = None, voiceprint_config: dict = None
    ) -> List[Dict[str, str]]:
        # 构建对话
        dialogue = []

        # 添加系统提示和记忆
        system_message = next(
            (msg for msg in self.dialogue if msg.role == "system"), None
        )

        if system_message:
            # 以 <context> 为分界点，拆分静态 system prompt 和动态上下文
            # 静态部分（规则、身份等）保持不变，可命中前缀缓存
            # 动态部分（时间、天气、记忆等）放到对话末尾的 user 消息中
            full_prompt = system_message.content
            context_match = re.search(r"<context>", full_prompt)
            if context_match:
                static_part = full_prompt[:context_match.start()]
                dynamic_part = full_prompt[context_match.start():]
            else:
                static_part = full_prompt
                dynamic_part = ""

            # 静态 system prompt：不含任何动态内容，前缀缓存可命中
            dialogue.append({"role": "system", "content": static_part})

        # 添加用户和助手的对话
        non_system_messages = [m for m in self.dialogue if m.role != "system"]
        complete_messages = self._ensure_tool_calls_complete(non_system_messages)
        for m in complete_messages:
            self.getMessages(m, dialogue)

        # 动态上下文：时间、记忆、说话人信息，放到对话末尾的 user 消息中
        if system_message and dynamic_part:
            # 替换时间占位符
            dynamic_part = dynamic_part.replace(
                "{{current_time}}", datetime.now().strftime("%H:%M")
            )

            # 填充记忆
            if memory_str is not None:
                dynamic_part = re.sub(
                    r"<memory>.*?</memory>",
                    f"<memory>\n{memory_str}\n</memory>",
                    dynamic_part,
                    flags=re.DOTALL,
                )

            # 追加说话人信息
            try:
                speakers = voiceprint_config.get("speakers", [])
                if speakers:
                    dynamic_part += "\n<speakers_info>"
                    for speaker_str in speakers:
                        try:
                            parts = speaker_str.split(",", 2)
                            if len(parts) >= 2:
                                name = parts[1].strip()
                                description = (
                                    parts[2].strip() if len(parts) >= 3 else ""
                                )
                                dynamic_part += f"\n- {name}：{description}"
                        except:
                            pass
                    dynamic_part += "\n</speakers_info>"
            except:
                pass

            dialogue.append({"role": "user", "content": dynamic_part})

        return dialogue
