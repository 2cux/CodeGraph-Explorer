"""Hook configuration model.

Defines HookConfig, the Pydantic model for post-commit hook state
stored within state.json.
"""

from pydantic import BaseModel, Field


class HookConfig(BaseModel):
    """Configuration and runtime state for the git post-commit auto-update hook.

    Stored in ``state.json`` under the ``"hook"`` key.
    """

    auto_update_on_commit: bool = Field(
        default=True,
        description="Whether to run incremental sync on each git commit",
    )
    installed: bool = Field(
        default=False,
        description="Whether the managed hook is currently installed",
    )
    installed_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp of last hook installation",
    )
    hook_path: str | None = Field(
        default=None,
        description="Absolute path to the installed hook script",
    )
    last_run_at: str | None = Field(
        default=None,
        description="ISO-8601 timestamp of last hook execution",
    )
    last_run_exit_code: int | None = Field(
        default=None,
        description="Exit code of last hook execution (0=success)",
    )
    last_run_duration_ms: float | None = Field(
        default=None,
        description="Duration of last hook execution in milliseconds",
    )
    total_runs: int = Field(
        default=0,
        description="Total number of hook invocations",
    )
    total_failures: int = Field(
        default=0,
        description="Total number of hook invocations that failed (non-zero exit)",
    )
