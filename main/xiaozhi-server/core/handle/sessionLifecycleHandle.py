"""会话生命周期处理器 - 处理会话的创建和销毁"""

from config.logger import setup_logging
from core.infrastructure.di.container import DIContainer, ServiceScope
from core.infrastructure.event.event_bus import EventBus
from core.infrastructure.event.event_types import SessionCreatedEvent, SessionDestroyingEvent
from core.utils.modules_initialize import initialize_tts, initialize_asr
from core.providers.tts.default import DefaultTTS


class SessionLifecycleHandler:
    """会话生命周期处理器 - 初始化和清理会话级服务"""

    def __init__(self, container: DIContainer, event_bus: EventBus):
        self.container = container
        self.event_bus = event_bus
        self.logger = setup_logging()

    async def handle_session_created(self, event: SessionCreatedEvent):
        """处理会话创建事件 - 初始化会话级服务"""
        session_id = event.session_id

        try:
            # 获取会话上下文
            context = self.container.resolve('session_context', session_id=session_id)
            if not context:
                self.logger.error(f"会话 {session_id} 的上下文不存在")
                return

            # 设置事件循环引用（用于线程安全的事件发布）
            import asyncio
            context._event_loop = asyncio.get_running_loop()
            self.logger.debug(f"会话 {session_id} 事件循环已设置")

            # 初始化系统提示词
            await self._initialize_system_prompt(context, session_id)

            # 初始化 TTS 服务
            tts = None
            if not context.need_bind:
                try:
                    tts = initialize_tts(context._config)
                    self.logger.debug(f"TTS 初始化成功: {type(tts).__name__}")
                except Exception as e:
                    self.logger.error(f"初始化 TTS 失败: {e}", exc_info=True)

            if tts is None:
                self.logger.warning(f"使用 DefaultTTS (占位符)")
                tts = DefaultTTS(context._config, delete_audio_file=True)

            # 注册 TTS 到容器（会话级）
            self.container.register(
                'tts',
                instance=tts,
                scope=ServiceScope.SESSION
            )
            # 手动添加到会话服务缓存
            if session_id not in self.container._session_services:
                self.container._session_services[session_id] = {}
            self.container._session_services[session_id]['tts'] = tts

            # 获取事件总线并打开音频通道
            event_bus = self.container.resolve('event_bus')
            await tts.open_audio_channels(context, self.container, event_bus)

            # 检查线程是否启动
            if hasattr(tts, 'tts_priority_thread') and tts.tts_priority_thread:
                self.logger.debug(f"会话 {session_id} TTS 文本处理线程状态: alive={tts.tts_priority_thread.is_alive()}")
            if hasattr(tts, 'audio_play_priority_thread') and tts.audio_play_priority_thread:
                self.logger.debug(f"会话 {session_id} TTS 音频播放线程状态: alive={tts.audio_play_priority_thread.is_alive()}")

            self.logger.debug(f"会话 {session_id} TTS 服务已初始化并启动")

            # 初始化 ASR 服务
            asr_service = None
            try:
                # 获取全局 ASR
                global_asr = self.container.resolve('asr')
                if global_asr:
                    from core.providers.asr.dto.dto import InterfaceType
                    if global_asr.interface_type == InterfaceType.LOCAL:
                        # 本地 ASR 可以共享
                        asr_service = global_asr
                    else:
                        # 远程 ASR 需要每个会话一个实例
                        asr_service = initialize_asr(context._config)
            except Exception as e:
                self.logger.debug(f"ASR 服务未启用或初始化失败: {e}")

            if asr_service:
                # 手动添加到会话服务缓存
                self.container._session_services[session_id]['asr_service'] = asr_service

                # 打开 ASR 音频通道
                # 检查 open_audio_channels 方法签名
                import inspect
                sig = inspect.signature(asr_service.open_audio_channels)
                # 获取参数列表（排除 self）
                params = [p for p in sig.parameters.values() if p.name != 'self']
                params_count = len(params)

                event_bus = self.container.resolve('event_bus')

                if params_count == 1:
                    # 只接收 context 参数的子类版本
                    await asr_service.open_audio_channels(context)
                elif params_count == 3:
                    # 接收 (context, container, event_bus) 的基类版本
                    await asr_service.open_audio_channels(context, self.container, event_bus)
                else:
                    # 未知签名，尝试使用3参数版本
                    self.logger.warning(f"ASR open_audio_channels 方法签名未知，参数数量: {params_count}")
                    await asr_service.open_audio_channels(context, self.container, event_bus)

                self.logger.debug(f"会话 {session_id} ASR 服务已初始化并启动")

            # 初始化 Memory 服务（如果需要）
            try:
                global_memory = self.container.resolve('memory')
                if global_memory:
                    # Memory 是会话级的，每个会话需要一个实例
                    if hasattr(global_memory, 'create_session_instance'):
                        memory_instance = global_memory.create_session_instance(session_id)
                    else:
                        # 如果不支持创建会话实例，直接使用全局实例
                        memory_instance = global_memory

                    self.container._session_services[session_id]['memory'] = memory_instance
                    self.logger.debug(f"会话 {session_id} Memory 服务已初始化")
            except Exception as e:
                self.logger.debug(f"Memory 服务未启用或初始化失败: {e}")

        except Exception as e:
            self.logger.error(f"处理会话创建事件失败: {e}", exc_info=True)

    async def _initialize_system_prompt(self, context, session_id: str):
        """初始化系统提示词

        Args:
            context: 会话上下文
            session_id: 会话ID
        """
        try:
            # 获取配置中的用户提示词
            user_prompt = context._config.get("prompt")
            if not user_prompt:
                self.logger.debug(f"会话 {session_id} 未配置系统提示词")
                return

            # 第一步：快速初始化 - 使用用户配置的提示词
            if context.prompt_manager:
                quick_prompt = context.prompt_manager.get_quick_prompt(user_prompt)
                if quick_prompt:
                    self._change_system_prompt(context, quick_prompt)
                    self.logger.debug(f"会话 {session_id} 快速初始化系统提示词成功: {quick_prompt[:50]}...")

            # 第二步：增强更新 - 添加上下文信息（时间、地点、IoT设备等）
            if context.prompt_manager:
                # 更新上下文信息
                context.prompt_manager.update_context_info(context, context.client_ip)

                # 构建增强的系统提示词
                enhanced_prompt = context.prompt_manager.build_enhanced_prompt(
                    user_prompt, context.device_id, context.client_ip
                )

                if enhanced_prompt:
                    self._change_system_prompt(context, enhanced_prompt)
                    self.logger.debug(f"会话 {session_id} 系统提示词已增强更新")

        except Exception as e:
            self.logger.error(f"会话 {session_id} 初始化系统提示词失败: {e}", exc_info=True)

    def _change_system_prompt(self, context, prompt: str):
        """更新系统提示词到会话上下文

        Args:
            context: 会话上下文
            prompt: 系统提示词
        """
        context.prompt = prompt
        if context.dialogue:
            context.dialogue.update_system_message(prompt)

    async def handle_session_destroying(self, event: SessionDestroyingEvent):
        """处理会话销毁事件 - 清理会话级服务"""
        session_id = event.session_id

        try:
            # 获取会话级服务
            if session_id not in self.container._session_services:
                return

            services = self.container._session_services[session_id]

            # 清理 TTS
            if 'tts' in services:
                tts = services['tts']
                if hasattr(tts, 'close'):
                    try:
                        await tts.close()
                    except Exception as e:
                        self.logger.error(f"关闭 TTS 失败: {e}")

            # 清理 ASR
            if 'asr_service' in services:
                asr = services['asr_service']
                if hasattr(asr, 'close'):
                    try:
                        await asr.close()
                    except Exception as e:
                        self.logger.error(f"关闭 ASR 失败: {e}")

            self.logger.debug(f"会话 {session_id} 的服务已清理")

        except Exception as e:
            self.logger.error(f"处理会话销毁事件失败: {e}", exc_info=True)


def register_session_lifecycle_handler(container: DIContainer, event_bus: EventBus):
    """注册会话生命周期处理器到事件总线"""
    handler = SessionLifecycleHandler(container, event_bus)
    event_bus.subscribe(SessionCreatedEvent, handler.handle_session_created)
    event_bus.subscribe(SessionDestroyingEvent, handler.handle_session_destroying)
    return handler
