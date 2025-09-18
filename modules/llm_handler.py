from __future__ import annotations

import logging
import os
import time
import re
from pathlib import Path
from typing import Any, Dict, Optional

from openai import OpenAI


class LLMHandler:
    """封装 LLM 调用与模板选择、重试逻辑。"""

    def __init__(self, config) -> None:  # ConfigManager 实例
        self.config = config
        # OpenAI v1 客户端（允许自定义 base_url 与 api_key）
        self.client = OpenAI(
            base_url=self.config.llm_api_base,
            api_key=self.config.llm_api_token or os.getenv("OPENAI_API_KEY", ""),
        )
        self.logger = logging.getLogger("audionote")

    def _read_text_file(self, path: str) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return None

    def _select_template(self, course_name: str) -> Dict[str, str]:
        clinical_courses = [c.strip() for c in self.config.clinical_courses if c.strip()]
        name_norm = (course_name or "").strip()
        is_clinical = any(
            c == name_norm or (c and (c in name_norm or name_norm in c))
            for c in clinical_courses
        )

        clinical_path = self.config.prompt_clinical_path
        general_path = self.config.prompt_general_path

        template_name = "clinical" if is_clinical else "general"
        template_path = clinical_path if is_clinical else general_path

        content = self._read_text_file(template_path)
        if not content:
            # 回退到通用模板
            if template_path != general_path:
                content = self._read_text_file(general_path)
                template_name = "general(fallback)"
                template_path = general_path
        if not content:
            # 最后兜底，给一个最简指令
            content = "你是资深教学助理，请将给定转录整理为结构化 Obsidian 笔记。"
            template_name = "builtin-minimal"

        self.logger.debug("[DEBUG] Selected LLM template: '%s'", template_name)
        return {"name": template_name, "path": template_path, "content": content}

    def _post_process_note(self, content: str) -> str:
        # 统一分割线
        s = content.replace("***", "---")
        # 修复 Anki 括号与序号：{cN::...} -> {{c1::...}}
        s = re.sub(r"\{c\d+::(.*?)\}", r"{{c1::\1}}", s)
        # 清理“一句话总结”标题行（保留正文）
        s = re.sub(r"(?mi)^\s*###\s*\d*\.?\s*(One-Sentence Summary|一句话总结)\s*\n", "", s)
        # 去除 Anki 段落中的列表前缀
        lines = s.splitlines()
        out_lines = []
        in_anki = False
        for line in lines:
            if re.match(r"^\s*##\s*🧠\s*Anki\s*卡片\s*$", line) or re.match(r"^\s*##\s*Anki\s*卡片\s*$", line):
                in_anki = True
                out_lines.append(line)
                continue
            if in_anki:
                if re.match(r"^\s*##\s+", line):
                    in_anki = False
                    out_lines.append(line)
                    continue
                out_lines.append(re.sub(r"^\s*-\s+", "", line))
            else:
                out_lines.append(line)
        return "\n".join(out_lines)

    def _render_prompt(self, template_text: str, transcript: str, course_info: Dict[str, Any], meta: Dict[str, Any]) -> str:
        # 按模板格式化：保持已填字段不变，仅让 LLM 填 [FILL_HERE] 的字段
        fmt = {
            "course_name": course_info.get("course_name", ""),
            "week_num": course_info.get("week_num", ""),
            "date": meta.get("date", ""),
            "sequence": meta.get("sequence", ""),
            "transcript_filename": meta.get("transcript_filename", ""),
            "transcript_text": transcript,
        }
        try:
            rendered = template_text.format(**fmt)
        except Exception:
            # 若模板变量不匹配，退化为简单拼接，避免中断
            rendered = (
                f"{template_text}\n\n"
                f"[METADATA_FOR_CONTEXT_ONLY]\n"
                f"Course Name: {fmt['course_name']}\nDate: {fmt['date']}\nWeek: {fmt['week_num']}\n"
                f"Sequence: {fmt['sequence']}\nTranscript File Name: {fmt['transcript_filename']}\n\n"
                f"[TRANSCRIPT]\n{fmt['transcript_text']}\n"
            )
        return rendered

    def generate_note(self, transcript: str, course_info: Dict[str, Any], meta: Dict[str, Any]) -> Optional[str]:
        system_prompt = self._read_text_file(self.config.prompt_system_path) or "You are a helpful assistant."
        template = self._select_template(course_info.get("course_name", ""))
        user_prompt = self._render_prompt(template["content"], transcript, course_info, meta)

        retries = max(1, int(self.config.llm_retry_count))
        delay = max(1, int(self.config.llm_retry_delay))
        self.logger.debug("[DEBUG] Using model=%s max_tokens=%s retries=%s delay=%s",
                          self.config.llm_model_name, self.config.llm_max_tokens, retries, delay)

        for attempt in range(1, retries + 1):
            try:
                resp = self.client.chat.completions.create(
                    model=self.config.llm_model_name,
                    temperature=0.2,
                    max_tokens=self.config.llm_max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                content = (resp.choices[0].message.content or "").strip()
                if content:
                    content = self._post_process_note(content)
                if content:
                    return content
                self.logger.warning("[WARN] LLM returned empty content. attempt=%d", attempt)
            except Exception as e:
                self.logger.error("[ERROR] LLM call failed (attempt %d/%d): %s", attempt, retries, e)
            if attempt < retries:
                time.sleep(delay)

        return None


