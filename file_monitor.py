from __future__ import annotations

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable

import pytz
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler

from modules.config_manager import ConfigManager
from modules.logger_config import setup_logger


SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")
AUDIO_PATTERNS = ["*.mp3", "*.m4a", "*.wav", "*.aac", "*.flac", "*.ogg", "*.m4b"]


def _has_std_prefix(name: str) -> bool:
    # YYYYMMDD-HHMMSS-
    import re
    return re.match(r"^\d{8}-\d{6}-", name) is not None


def _unique_path(dir_path: Path, base_name: str) -> Path:
    target = dir_path / base_name
    if not target.exists():
        return target
    stem, ext = os.path.splitext(base_name)
    i = 1
    while True:
        candidate = dir_path / f"{stem}-{i}{ext}"
        if not candidate.exists():
            return candidate
        i += 1


class AudioCreateHandler(PatternMatchingEventHandler):
    def __init__(self, logger: logging.Logger):
        super().__init__(patterns=AUDIO_PATTERNS, ignore_directories=True)
        self.logger = logger

    def on_created(self, event):  # type: ignore[override]
        path = Path(event.src_path)
        try:
            # 等待文件写入稳定
            last_size = -1
            for _ in range(20):
                size = path.stat().st_size if path.exists() else -1
                if size == last_size and size > 0:
                    break
                last_size = size
                time.sleep(0.5)

            if _has_std_prefix(path.name):
                return

            now = datetime.now(SHANGHAI_TZ)
            ts = now.strftime("%Y%m%d-%H%M%S")
            new_name = f"{ts}-{path.name}"
            target = _unique_path(path.parent, new_name)
            path.rename(target)
            self.logger.info("[INFO] Renamed audio file: '%s' -> '%s'", path.name, target.name)
        except Exception as e:
            self.logger.error("[ERROR] Failed to rename '%s': %s", path.name, e)


def main() -> None:
    config = ConfigManager()
    logger = setup_logger(config.log_file_path)
    audio_dir = Path(config.audio_dir)
    audio_dir.mkdir(parents=True, exist_ok=True)

    event_handler = AudioCreateHandler(logger)
    observer = Observer()
    observer.schedule(event_handler, str(audio_dir), recursive=False)

    logger.info("[INFO] Audio file monitor started at: %s", audio_dir)
    observer.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("[INFO] Stopping monitor ...")
    finally:
        observer.stop()
        observer.join()


if __name__ == "__main__":
    main()


