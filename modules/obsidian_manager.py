from __future__ import annotations

import re
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict


def _sanitize_filename(name: str) -> str:
    # 移除不安全字符并裁剪长度
    name = re.sub(r"[\\/:*?\"<>|]", " ", name).strip()
    name = re.sub(r"\s+", " ", name)
    return name[:120]


@dataclass
class ObsidianManager:
    vault_path: str
    course_info: Dict[str, Any]

    def __post_init__(self) -> None:
        self.course_name = self.course_info.get("course_name", "Course") or "Course"
        self.week_num = int(self.course_info.get("week_num", 0) or 0)
        self.base_dir = Path(self.vault_path) / _sanitize_filename(self.course_name)
        # 纪要直接写入课程根目录（不创建 Notes 子目录）
        self.notes_dir = self.base_dir
        # 转录稿写入 Transcripts 子目录
        self.transcripts_dir = self.base_dir / "Transcripts"
        for d in [self.base_dir, self.transcripts_dir]:
            d.mkdir(parents=True, exist_ok=True)
        import logging
        self.logger = logging.getLogger("audionote")

    def get_next_sequence_num(self) -> int:
        max_seq = 0
        pattern = re.compile(r"^(\d{3})-.*\.md$", re.IGNORECASE)
        for path in self.notes_dir.glob("*.md"):
            m = pattern.match(path.name)
            # 排除转录稿副本（仅计入纪要）
            if m and "Transcript" not in path.name:
                try:
                    max_seq = max(max_seq, int(m.group(1)))
                except ValueError:
                    pass
        return max_seq + 1

    def save_transcript(self, sequence_num: int, transcript_content: str) -> Path:
        week_part = f"W{self.week_num:02d}"
        course_name_part = _sanitize_filename(self.course_name)
        filename = f"{sequence_num:03d}-{week_part}-{course_name_part}-Transcript.md"
        path = self.transcripts_dir / filename
        path.write_text(transcript_content, encoding="utf-8")
        return path

    def _parse_topic(self, md_content: str) -> str:
        content = md_content
        if "```yaml" in content:
            try:
                part = content.split("```yaml", 1)[1]
                yaml_block, rest = part.split("```", 1)
                content = f"---\n{yaml_block.strip()}\n---\n{rest}"
            except Exception as e:
                self.logger.warning("[WARN] YAML code fence parse failed: %s", e)

        lines = content.strip().splitlines()
        # 1) 优先解析 YAML Frontmatter 的 topic
        if lines and lines[0].strip() == "---":
            try:
                yaml_lines = []
                for i in range(1, len(lines)):
                    if lines[i].strip() == "---":
                        break
                    yaml_lines.append(lines[i])
                for raw in yaml_lines:
                    s = raw.strip()
                    if not s or s.startswith("#"):
                        continue
                    if ":" in s:
                        k, v = s.split(":", 1)
                        if k.strip().lower() == "topic":
                            topic = v.strip().strip('"').strip("'")
                            if topic:
                                self.logger.debug("[DEBUG] Parsed topic from YAML: '%s'", topic)
                                return _sanitize_filename(topic)
            except Exception as e:
                self.logger.error("[ERROR] Failed to parse YAML topic: %s", e, exc_info=True)
                # 不中断，继续回退

        # 2) 回退：取首个一级标题作为主题
        for line in lines:
            if line.strip().startswith("# "):
                topic = line.strip().lstrip("# ").strip()
                if topic:
                    self.logger.warning("[WARN] YAML topic not found, fell back to H1 title: '%s'", topic)
                    return _sanitize_filename(topic)

        # 3) 最终兜底
        self.logger.error("[ERROR] Could not determine topic from LLM response. Using 'Untitled'.")
        return "Untitled"

    def save_note(self, sequence_num: int, md_content: str) -> Path:
        topic = self._parse_topic(md_content)
        week_part = f"W{self.week_num:02d}-" if self.week_num > 0 else ""
        filename = f"{sequence_num:03d}-{week_part}{topic}.md"
        final_path = self.notes_dir / filename

        # 原子写入：写到同目录的临时文件后再重命名
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(self.notes_dir)) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(md_content)

        os.replace(tmp_path, final_path)  # 原子移动（同分区）
        return final_path


