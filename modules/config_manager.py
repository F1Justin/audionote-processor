import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional

from dotenv import load_dotenv


def _parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class ConfigManager:
    """统一管理 .env 配置，提供便捷的取值与类型转换。"""

    env_loaded: bool = False

    def __post_init__(self) -> None:
        # 尝试从项目根目录加载 .env
        self.env_loaded = load_dotenv(override=False)

    def get(self, key: str, default: Optional[Any] = None, cast: Optional[Callable[[str], Any]] = None) -> Any:
        raw = os.getenv(key)
        if raw is None:
            return default
        if cast is None:
            return raw
        if cast is bool:
            return _parse_bool(raw)
        try:
            return cast(raw)
        except Exception:
            return default

    def get_path(self, key: str, default: Optional[str] = None) -> str:
        raw = os.getenv(key, default if default is not None else "")
        # 使用原始路径，不做 expanduser
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
        return str(path.resolve())

    def get_list(self, key: str, sep: str = ",") -> List[str]:
        raw = os.getenv(key, "")
        if not raw:
            return []
        return [item.strip() for item in raw.split(sep) if item.strip()]

    # 便捷取值
    @property
    def audio_dir(self) -> str:
        return self.get_path("AUDIO_DIR", "./audio")

    @property
    def transcript_dir(self) -> str:
        return self.get_path("TRANSCRIPT_DIR", "./transcripts")

    @property
    def processed_transcript_dir(self) -> str:
        return self.get_path("PROCESSED_TRANSCRIPT_DIR", "./transcripts/processed")

    @property
    def obsidian_vault_path(self) -> str:
        return self.get_path("OBSIDIAN_VAULT_PATH", "./obsidian_vault")

    @property
    def ics_file_path(self) -> str:
        # 优先使用根目录的 schedule.ics（如存在），否则回退到 ENV 或默认 your_schedule.ics
        from pathlib import Path
        schedule_alt = Path.cwd() / "schedule.ics"
        if schedule_alt.exists():
            return str(schedule_alt.resolve())
        return self.get_path("ICS_FILE_PATH", "./your_schedule.ics")

    @property
    def log_file_path(self) -> str:
        return self.get_path("LOG_FILE_PATH", "./processor.log")

    @property
    def enable_auto_rename(self) -> bool:
        return self.get("ENABLE_AUTO_RENAME", False, bool)

    @property
    def semester_start_date(self) -> str:
        return self.get("SEMESTER_START_DATE", "2025-09-15")

    @property
    def clinical_courses(self) -> List[str]:
        return self.get_list("CLINICAL_COURSES")

    # LLM 参数
    @property
    def llm_api_base(self) -> str:
        return self.get("LLM_API_BASE", "https://api.openai.com/v1")

    @property
    def llm_api_token(self) -> str:
        return self.get("LLM_API_TOKEN", "")

    @property
    def llm_model_name(self) -> str:
        return self.get("LLM_MODEL_NAME", "gpt-4o-mini")

    @property
    def llm_retry_count(self) -> int:
        return int(self.get("LLM_RETRY_COUNT", 3))

    @property
    def llm_retry_delay(self) -> int:
        return int(self.get("LLM_RETRY_DELAY", 5))

    @property
    def llm_max_tokens(self) -> int:
        return int(self.get("LLM_MAX_TOKENS", 20000))

    # Prompt 路径
    @property
    def prompt_system_path(self) -> str:
        return self.get_path("PROMPT_SYSTEM_PATH", "./prompts/system_prompt.txt")

    @property
    def prompt_general_path(self) -> str:
        return self.get_path("PROMPT_GENERAL_PATH", "./prompts/general_template.txt")

    @property
    def prompt_clinical_path(self) -> str:
        # 允许文件不存在，调用方应处理回退
        return self.get_path("PROMPT_CLINICAL_PATH", "./prompts/clinical_template.txt")

    # Logging
    @property
    def log_level(self) -> int:
        name = str(self.get("LOG_LEVEL", "INFO")).strip().upper()
        return getattr(logging, name, logging.INFO)


