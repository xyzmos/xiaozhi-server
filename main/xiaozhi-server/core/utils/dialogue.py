import uuid
import re
import logging
import asyncio
import threading
import os
from typing import List, Dict, Optional
from datetime import datetime

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_prompt_template(file_path: str) -> str:
    """加载提示词模板文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


class Message:
    def __init__(
        self,
        role: str,
        content: str = None,
        uniq_id: str = None,
        tool_calls=None,
        tool_call_id=None,
        is_temporary: bool = False,
    ):
        self.uniq_id = uniq_id if uniq_id is not None else str(uuid.uuid4())
        self.role = role
        self.content = content
        self.tool_calls = tool_calls
        self.tool_call_id = tool_call_id
        self.is_temporary = is_temporary  # 标记临时消息（如工具调用提醒）


class Dialogue:
    def __init__(self, config: dict = None, logger: logging.Logger = None):
        self.dialogue: List[Message] = []
        self.logger = logger

        # 从配置中读取最大历史轮数，默认为 6 轮
        if config:
            self.max_history_turns = config.get("max_history_turns", 6)
            # 周期性摘要配置
            self.enable_summary = config.get("enable_history_summary", False)
            self.summary_interval = config.get("summary_interval", 8)
            # 历史截断开关配置（默认关闭）
            self.enable_truncation = config.get("enable_history_truncation", False)
            # 摘要提示词模板文件
            self.summary_prompt_file = config.get("summary_prompt_template", "summary-prompt.txt")
            self.summary_merge_prompt_file = config.get("summary_merge_prompt_template", "summary-merge-prompt.txt")
        else:
            self.max_history_turns = 6
            self.enable_summary = False
            self.summary_interval = 8
            self.enable_truncation = False
            self.summary_prompt_file = "summary-prompt.txt"
            self.summary_merge_prompt_file = "summary-merge-prompt.txt"

        # 摘要相关状态
        self._history_summary: Optional[str] = None  # 历史摘要缓存
        self._summary_task: Optional[asyncio.Task] = None  # 后台摘要任务
        self._turn_counter: int = 0  # 用户轮次计数器

        # 预加载并缓存提示词模板
        self._summary_prompt_template: str = ""
        self._summary_merge_prompt_template: str = ""
        self._load_summary_templates()

    def _load_summary_templates(self):
        """预加载摘要提示词模板（启动时加载一次，避免频繁IO）"""
        try:
            summary_prompt_path = os.path.join(PROJECT_ROOT, self.summary_prompt_file)
            self._summary_prompt_template = _load_prompt_template(summary_prompt_path)
        except Exception as e:
            self._summary_prompt_template = ""

        try:
            merge_prompt_path = os.path.join(PROJECT_ROOT, self.summary_merge_prompt_file)
            self._summary_merge_prompt_template = _load_prompt_template(merge_prompt_path)
        except Exception as e:
            self._summary_merge_prompt_template = ""

    def _log_debug(self, msg: str):
        if self.logger:
            self.logger.debug(msg)

    def put(self, message: Message):
        self.dialogue.append(message)
        # 用户消息时递增轮次计数器
        if message.role == "user":
            self._turn_counter += 1

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

    def _group_messages_by_turns(self, messages: List[Message]) -> List[List[Message]]:
        """
        将消息按对话轮次分组
        """
        turns = []
        current_turn = []

        for msg in messages:
            if msg.role == "user":
                if current_turn:
                    turns.append(current_turn)
                current_turn = [msg]
            else:
                current_turn.append(msg)

        if current_turn:
            turns.append(current_turn)

        return turns

    def _ensure_tool_calls_complete(self, messages: List[Message]) -> List[Message]:
        """
        确保所有 tool_calls 都有对应的 tool 响应
        
        修复被打断导致的悬空 tool_calls，防止大模型 API 报 400 错误
        """
        pending_tool_calls = set()
        result = []

        for msg in messages:
            result.append(msg)

            # 记录 assistant 发出的 tool_calls ID
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    # 兼容字典和对象两种格式
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tc_id:
                        pending_tool_calls.add(tc_id)

            # tool 响应核销对应的 ID
            elif msg.role == "tool" and msg.tool_call_id:
                pending_tool_calls.discard(msg.tool_call_id)

        # 为悬空的 tool_calls 补齐占位响应
        for missing_id in pending_tool_calls:
            dummy_tool_msg = Message(
                role="tool",
                content='{"status": "interrupted", "message": "动作已取消/被打断"}',
                tool_call_id=missing_id
            )
            result.append(dummy_tool_msg)
            self._log_debug(f"已为悬空的 tool_call({missing_id}) 自动补齐占位响应")

        return result

    async def _do_periodic_summary(self, llm_client):
        """
        异步生成周期性摘要

        提取窗口外的早期对话轮次，调用LLM生成摘要，支持增量合并。
        全程try/except静默降级，不影响主流程。
        """
        SUMMARY_MAX_LENGTH = 400  # 摘要硬上限
        CONTENT_TRUNCATE_LENGTH = 200  # 每条消息截断长度

        try:
            # 获取非system消息
            non_system_messages = [m for m in self.dialogue if m.role != "system"]
            if not non_system_messages:
                return

            # 找到最后一个user的位置（当前轮次的起点）
            last_user_idx = -1
            for i in range(len(non_system_messages) - 1, -1, -1):
                if non_system_messages[i].role == "user":
                    last_user_idx = i
                    break

            if last_user_idx <= 0:
                return  # 没有历史消息或只有当前轮

            # 历史消息（排除当前轮）
            history_messages = non_system_messages[:last_user_idx]

            # 按轮次分组
            history_turns = self._group_messages_by_turns(history_messages)

            # 取出窗口外的早期轮次（排除最近的 max_history_turns 轮）
            if len(history_turns) <= self.max_history_turns:
                self._log_debug(f"历史轮次({len(history_turns)})未超过窗口({self.max_history_turns})，无需摘要")
                return

            early_turns = history_turns[:-self.max_history_turns]

            # 拼接早期对话文本（跳过tool类型消息）
            conversation_text = ""
            for turn in early_turns:
                for msg in turn:
                    if msg.role == "tool":
                        continue  # 跳过tool消息
                    if msg.content:
                        truncated = msg.content[:CONTENT_TRUNCATE_LENGTH]
                        role_label = "用户" if msg.role == "user" else "助手"
                        conversation_text += f"{role_label}: {truncated}\n"

            if not conversation_text.strip():
                return

            self._log_debug(f"开始生成周期性摘要，早期对话共{len(early_turns)}轮")

            # 构建摘要prompt（使用缓存的模板）
            summary_prompt = self._summary_prompt_template.replace("{{conversation_text}}", conversation_text)

            # 调用LLM生成摘要
            new_summary = llm_client.response_no_stream(
                system_prompt="你是一个对话摘要助手，擅长将长对话压缩为简洁的摘要。",
                user_prompt=summary_prompt
            )

            if not new_summary or not new_summary.strip():
                self._log_debug("LLM返回空摘要，跳过")
                return

            new_summary = new_summary.strip()
            self._log_debug(f"周期性摘要生成完成，未合并前内容: {new_summary}")

            # 如果已有摘要，进行增量合并（使用缓存的模板）
            if self._history_summary:
                merge_prompt = self._summary_merge_prompt_template.replace("{{existing_summary}}", self._history_summary)
                merge_prompt = merge_prompt.replace("{{new_summary}}", new_summary)

                merged_summary = llm_client.response_no_stream(
                    system_prompt="你是一个摘要合并助手，擅长将多段摘要合并为简洁的统一摘要。",
                    user_prompt=merge_prompt
                )
                if merged_summary and merged_summary.strip():
                    new_summary = merged_summary.strip()

            # 截断到硬上限
            if len(new_summary) > SUMMARY_MAX_LENGTH:
                new_summary = new_summary[:SUMMARY_MAX_LENGTH] + "..."

            # 更新摘要缓存
            self._history_summary = new_summary
            self._log_debug(f"周期性摘要生成完成，长度: {len(new_summary)}字符")
            self._log_debug(f"周期性摘要生成完成，合并后内容: {new_summary}")

        except Exception as e:
            # 静默降级，不影响主流程
            if self.logger:
                self.logger.warning(f"周期性摘要生成失败，已静默降级: {e}")

    def maybe_trigger_summary(self, llm_client) -> bool:
        """
        检查并触发周期性摘要生成

        触发条件：
        1. enable_summary 为 True
        2. _turn_counter > 0 且能被 summary_interval 整除
        3. 当前没有正在运行的摘要任务

        Args:
            llm_client: LLM 客户端实例

        Returns:
            bool: 是否成功触发了摘要任务
        """
        # 条件1: 检查功能是否开启
        if not self.enable_summary:
            return False

        # 条件2: 检查轮次是否达到触发间隔
        if self._turn_counter <= 0 or self._turn_counter % self.summary_interval != 0:
            return False

        # 条件3: 检查是否有正在运行的摘要任务
        if self._summary_task is not None and not self._summary_task.done():
            self._log_debug(f"摘要任务已在运行中，跳过触发 (turn={self._turn_counter})")
            return False

        # 满足所有条件，启动后台摘要任务
        # 使用线程安全的方式启动异步任务（兼容同步和异步上下文）
        try:
            loop = asyncio.get_running_loop()
            # 在已有事件循环中，使用 create_task
            self._summary_task = asyncio.create_task(self._do_periodic_summary(llm_client))
        except RuntimeError:
            # 没有运行中的事件循环，在新线程中启动
            def run_async_task():
                asyncio.run(self._do_periodic_summary(llm_client))

            thread = threading.Thread(target=run_async_task, daemon=True)
            thread.start()
            self._log_debug(f"已在新线程中触发周期性摘要任务 (turn={self._turn_counter})")

        self._log_debug(f"已触发周期性摘要任务 (turn={self._turn_counter})")
        return True

    def get_llm_dialogue_with_memory(
        self,
        memory_str: str = None,
        voiceprint_config: dict = None
    ) -> List[Dict[str, str]]:
        # 构建对话
        dialogue = []

        # 添加系统提示和记忆
        system_message = next(
            (msg for msg in self.dialogue if msg.role == "system"), None
        )

        if system_message:
            # 基础系统提示
            enhanced_system_prompt = system_message.content
            # 替换时间占位符
            enhanced_system_prompt = enhanced_system_prompt.replace(
                "{{current_time}}", datetime.now().strftime("%H:%M")
            )

            # 添加说话人个性化描述
            if voiceprint_config:
                try:
                    speakers = voiceprint_config.get("speakers", [])
                    if speakers:
                        enhanced_system_prompt += "\n\n<speakers_info>"
                        for speaker_str in speakers:
                            try:
                                parts = speaker_str.split(",", 2)
                                if len(parts) >= 2:
                                    name = parts[1].strip()
                                    description = parts[2].strip() if len(parts) >= 3 else ""
                                    enhanced_system_prompt += f"\n- {name}：{description}"
                            except Exception:
                                pass
                        enhanced_system_prompt += "\n\n</speakers_info>"
                except Exception:
                    pass

            # 注入记忆内容
            if memory_str is not None:
                enhanced_system_prompt = re.sub(
                    r"<memory>.*?</memory>",
                    f"<memory>\n{memory_str}\n</memory>",
                    enhanced_system_prompt,
                    flags=re.DOTALL,
                )

            # 注入历史摘要（周期性摘要功能）
            if self.enable_summary and self._history_summary:
                enhanced_system_prompt += (
                    f"\n\n<earlier_conversation_summary>\n"
                    f"{self._history_summary}\n"
                    f"</earlier_conversation_summary>"
                )
                self._log_debug(f"已注入历史摘要到系统消息，长度: {len(self._history_summary)}字符")

            # dialogue.append({"role": "system", "content": enhanced_system_prompt})

        # 获取非系统消息
        non_system_messages = [m for m in self.dialogue if m.role != "system"]

        if not non_system_messages:
            return dialogue

        # 找到最后一个 user 的位置（当前轮次的起点）
        last_user_idx = -1
        for i in range(len(non_system_messages) - 1, -1, -1):
            if non_system_messages[i].role == "user":
                last_user_idx = i
                break

        # 如果没有 user 消息，直接返回
        if last_user_idx == -1:
            for m in non_system_messages:
                self.getMessages(m, dialogue)
            return dialogue

        # 历史轮次：截断并确保完整性
        history_messages = non_system_messages[:last_user_idx]
        # 当前轮次：原封不动保留
        current_turn_messages = non_system_messages[last_user_idx:]

        # 处理历史轮次
        if history_messages:
            history_turns = self._group_messages_by_turns(history_messages)

            # 根据截断开关决定是否截断历史轮次
            if self.enable_truncation:
                max_history = self.max_history_turns
                if max_history < 1:
                    max_history = 1

                if len(history_turns) > max_history:
                    history_turns = history_turns[-max_history:]

            for turn in history_turns:
                complete_turn = self._ensure_tool_calls_complete(turn)
                for m in complete_turn:
                    self.getMessages(m, dialogue)

        # 当前轮次原封不动保留
        for m in current_turn_messages:
            self.getMessages(m, dialogue)

        return dialogue