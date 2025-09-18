from __future__ import annotations

import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

import pytz

from modules.config_manager import ConfigManager
from modules.logger_config import setup_logger
from modules.ics_parser import ICSParser
from modules.text_utils import to_simplified
from modules.llm_handler import LLMHandler
from modules.obsidian_manager import ObsidianManager
import sys


SHANGHAI_TZ = pytz.timezone("Asia/Shanghai")


def _extract_timestamp_from_filename(name: str) -> Optional[datetime]:
    # 期待格式：YYYYMMDD-HHMMSS-...，若匹配失败尝试在任意位置提取
    m = re.match(r"^(\d{8}-\d{6})-", name)
    if not m:
        m = re.search(r"(\d{8}-\d{6})", name)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%Y%m%d-%H%M%S")
        return SHANGHAI_TZ.localize(dt)
    except Exception:
        return None


def main() -> None:
    # 1) 初始化
    config = ConfigManager()
    logger = setup_logger(config.log_file_path, config.log_level)
    logger.info("[INFO] System initializing ...")

    ics_parser = ICSParser(config.ics_file_path, config.semester_start_date)
    logger.info("[INFO] System initialized. Calendar loaded.")
    logger.debug("[DEBUG] CONFIG: audio=%s, transcript=%s, processed=%s, vault=%s, ics=%s, model=%s",
                 config.audio_dir, config.transcript_dir, config.processed_transcript_dir,
                 config.obsidian_vault_path, config.ics_file_path, config.llm_model_name)

    # 2) 扫描
    transcript_dir = Path(config.transcript_dir)
    transcript_dir.mkdir(parents=True, exist_ok=True)
    files = sorted([p for p in transcript_dir.glob("*.txt") if p.is_file()])
    if not files:
        logger.info("[INFO] Found 0 new transcripts. Nothing to do.")
        return
    logger.info("[INFO] Found %d new transcripts. Starting processing.", len(files))

    llm = LLMHandler(config)

    # 3) 处理循环
    for path in files:
        file_name = path.name
        logger.info("[INFO] >>> Processing: %s", file_name)

        # a) 上下文构建
        timestamp_dt = _extract_timestamp_from_filename(file_name)
        if timestamp_dt is None:
            try:
                ctime = datetime.fromtimestamp(path.stat().st_ctime, tz=SHANGHAI_TZ)
                timestamp_dt = ctime
                logger.warning("[WARN] Timestamp not found in filename, fallback to ctime: %s", ctime)
            except Exception:
                logger.error("[ERROR] Cannot determine timestamp. Skipping file: %s", file_name)
                logger.info("[INFO] <<< Finished: %s", file_name)
                continue

        course_info = ics_parser.match_course(timestamp_dt)
        if course_info is None:
            try:
                user_input = input(
                    f"未匹配到课程信息，手动输入课程名称（回车跳过）[{file_name}]: "
                ).strip()
            except Exception:
                user_input = ""
            if not user_input:
                logger.error("[ERROR] Course matching failed and user skipped: %s", file_name)
                logger.info("[INFO] <<< Finished: %s", file_name)
                continue
            from modules.ics_parser import ICSParser as _IP
            course_info = {"course_name": user_input, "week_num": _IP._calc_week_num(ics_parser, timestamp_dt)}

        # b) 文本预处理
        try:
            raw_text = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("[ERROR] Read transcript failed: %s | %s", file_name, e)
            logger.info("[INFO] <<< Finished: %s", file_name)
            continue
        processed_text = to_simplified(raw_text)

        # c) 预计算 Obsidian 路径与序号、日期、转录稿文件名
        manager = ObsidianManager(config.obsidian_vault_path, course_info)
        seq = manager.get_next_sequence_num()
        date_str = timestamp_dt.strftime("%Y-%m-%d")
        transcript_filename = f"{seq:03d}-W{course_info.get('week_num', 0):02d}-{manager.course_name}-Transcript.md"
        meta = {
            "sequence": seq,
            "date": date_str,
            "transcript_filename": transcript_filename,
        }
        logger.debug("[DEBUG] META: seq=%s date=%s transcript=%s", seq, date_str, transcript_filename)

        # d) LLM 处理（填空题模式）
        note_md = llm.generate_note(processed_text, course_info, meta)
        if not note_md:
            logger.fatal("[FATAL] LLM processing failed. Keep source for retry: %s", file_name)
            sys.exit(2)

        # e) Obsidian 归档（原子）
        try:
            manager.save_transcript(seq, processed_text)
            manager.save_note(seq, note_md)
            logger.info(
                "[SUCCESS] Transcript and Note for '%s' Week %s have been saved.",
                course_info.get("course_name", ""),
                course_info.get("week_num", ""),
            )
        except Exception as e:
            logger.fatal("[FATAL] Obsidian save failed: %s | file=%s", e, file_name)
            sys.exit(3)

        # f) 源文件归档
        try:
            processed_dir = Path(config.processed_transcript_dir)
            processed_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(processed_dir / file_name))
            logger.info("[INFO] Archived source file: %s", file_name)
        except Exception as e:
            logger.fatal("[FATAL] Move source to archive failed: %s | %s", file_name, e)
            sys.exit(4)

        logger.info("[INFO] <<< Finished: %s", file_name)

    # 4) 结束
    logger.info("[INFO] All tasks completed. Shutting down.")


if __name__ == "__main__":
    main()


