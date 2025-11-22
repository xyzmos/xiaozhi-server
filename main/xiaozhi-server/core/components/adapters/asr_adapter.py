from typing import Any, Dict
from core.components.component_manager import Component, ComponentType, ComponentFactory
from core.utils import asr
from core.utils.modules_initialize import initialize_asr
from config.logger import setup_logging

logger = setup_logging()


class ASRAdapter(Component):
    """ASR组件适配器：将现有ASR组件包装为新的组件接口"""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(ComponentType.ASR, config)
        self._asr_instance = None
        self._delete_audio = config.get("delete_audio", True)
    
    async def _do_initialize(self, context: Any) -> None:
        """初始化ASR组件"""
        try:
            # 获取ASR配置
            selected_module = self.config.get("selected_module", {}).get("ASR")
            if not selected_module:
                raise ValueError("未配置ASR模块")
            
            # 创建ASR实例
            self._asr_instance = initialize_asr(self.config)
            
            # 注册资源以便清理
            self.add_resource(self._asr_instance)
            
            # 打开音频通道
            if hasattr(self._asr_instance, 'open_audio_channels'):
                await self._asr_instance.open_audio_channels(context)
            
            logger.info(f"ASR组件初始化完成: {selected_module}")
            
        except Exception as e:
            logger.error(f"ASR组件初始化失败: {e}")
            raise
    
    async def _do_cleanup(self) -> None:
        """清理ASR组件"""
        if self._asr_instance:
            try:
                # 关闭ASR实例
                if hasattr(self._asr_instance, 'close'):
                    await self._asr_instance.close()
                
                # 清理音频文件
                if hasattr(self._asr_instance, 'cleanup_audio_files'):
                    self._asr_instance.cleanup_audio_files()
                
                logger.info("ASR组件清理完成")
                
            except Exception as e:
                logger.error(f"ASR组件清理失败: {e}")
            finally:
                self._asr_instance = None
    
    @property
    def asr_instance(self):
        """获取ASR实例"""
        return self._asr_instance


class ASRFactory(ComponentFactory):
    """ASR组件工厂"""
    
    def create(self, config: Dict[str, Any]) -> Component:
        return ASRAdapter(config)
    
    def get_component_type(self) -> ComponentType:
        return ComponentType.ASR


