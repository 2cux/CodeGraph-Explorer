"""CodeGraph git hook management.

Provides:
- HookManager: install/uninstall/status of git post-commit hooks
- HookConfig: Pydantic model for hook configuration
- get_hook_logger: rotating file logger for hook events
"""

from codegraph.hooks.config import HookConfig
from codegraph.hooks.logger import get_hook_logger
from codegraph.hooks.manager import HookManager

__all__ = ["HookManager", "HookConfig", "get_hook_logger"]
