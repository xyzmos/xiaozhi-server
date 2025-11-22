"""服务端插件工具执行器"""

import inspect
from typing import Dict, Any, TYPE_CHECKING
from ..base import ToolType, ToolDefinition, ToolExecutor
from plugins_func.register import all_function_registry, Action, ActionResponse, PluginContext

if TYPE_CHECKING:
    from core.infrastructure.di.container import DIContainer


class ServerPluginExecutor(ToolExecutor):
    """服务端插件工具执行器"""

    def __init__(self, container: 'DIContainer', session_id: str):
        self.container = container
        self.session_id = session_id
        self.context = container.resolve('session_context', session_id=session_id)
        self.config = self.context._config

    async def execute(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行服务端插件工具"""
        func_item = all_function_registry.get(tool_name)
        if not func_item:
            return ActionResponse(
                action=Action.NOTFOUND, response=f"插件函数 {tool_name} 不存在"
            )

        try:
            # 创建PluginContext
            event_bus = self.container.resolve('event_bus')
            plugin_context = PluginContext(
                session_id=self.session_id,
                container=self.container,
                event_bus=event_bus
            )

            # 根据工具类型决定如何调用
            if hasattr(func_item, "type"):
                func_type = func_item.type
                if func_type.code in [4, 5]:  # SYSTEM_CTL, IOT_CTL (需要PluginContext参数)
                    result = func_item.func(plugin_context, **arguments)
                elif func_type.code == 2:  # WAIT
                    result = func_item.func(**arguments)
                elif func_type.code == 3:  # CHANGE_SYS_PROMPT
                    result = func_item.func(plugin_context, **arguments)
                else:
                    result = func_item.func(**arguments)
            else:
                # 默认不传context参数
                result = func_item.func(**arguments)

            # 如果结果是协程，await它
            if inspect.iscoroutine(result):
                result = await result

            return result

        except Exception as e:
            return ActionResponse(
                action=Action.ERROR,
                response=str(e),
            )

    def get_tools(self) -> Dict[str, ToolDefinition]:
        """获取所有注册的服务端插件工具"""
        tools = {}

        # 获取必要的函数
        necessary_functions = ["handle_exit_intent", "get_lunar"]

        # 获取配置中的函数
        config_functions = self.config["Intent"][
            self.config["selected_module"]["Intent"]
        ].get("functions", [])

        # 转换为列表
        if not isinstance(config_functions, list):
            try:
                config_functions = list(config_functions)
            except TypeError:
                config_functions = []

        # 合并所有需要的函数
        all_required_functions = list(set(necessary_functions + config_functions))

        for func_name in all_required_functions:
            func_item = all_function_registry.get(func_name)
            if func_item:
                # 从函数注册中获取描述
                fun_description = (
                    self.config.get("plugins", {})
                    .get(func_name, {})
                    .get("description", "")
                )
                if fun_description is not None and len(fun_description) > 0:
                    if "function" in func_item.description and isinstance(
                        func_item.description["function"], dict
                    ):
                        func_item.description["function"][
                            "description"
                        ] = fun_description
                tools[func_name] = ToolDefinition(
                    name=func_name,
                    description=func_item.description,
                    tool_type=ToolType.SERVER_PLUGIN,
                )

        return tools

    def has_tool(self, tool_name: str) -> bool:
        """检查是否有指定的服务端插件工具"""
        return tool_name in all_function_registry
