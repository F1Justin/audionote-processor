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
        # 规范化 Anki 标题：兼容 ##/###、是否含表情、英文/中文写法
        s = re.sub(
            r"(?mi)^\s*#{2,}\s*(?:🧠\s*)?(?:Anki\s*卡片|Anki\s*Cards|Anki)\s*$",
            "## 🧠 Anki 卡片",
            s,
        )
        # 将 cloze 仅保留在 Anki 部分：
        # 1) 先整体修复 Anki 括号与序号：{cN::...} -> {{c1::...}}
        s = re.sub(r"\{c\d+::(.*?)\}", r"{{c1::\1}}", s)           # 单大括号 → 双大括号 c1
        s = re.sub(r"\{\{c\d+::(.*?)\}\}", r"{{c1::\1}}", s)      # 双大括号 cN → c1
        # 2) 在非 Anki 段落中，去掉任何 {{c1::...}} 标记，仅保留内部文字
        lines = s.splitlines()
        out_lines = []
        in_anki = False
        for line in lines:
            if re.match(r"^\s*##\s*🧠\s*Anki\s*卡片\s*$", line) or re.match(r"^\s*##\s*Anki\s*卡片\s*$", line):
                in_anki = True
                out_lines.append(line)
                continue
            if in_anki:
                # 保留 Anki 段落内容
                out_lines.append(line)
                # 离开段落：遇到下一节标题
                if re.match(r"^\s*##\s+", line):
                    in_anki = False
            else:
                # 非 anki 段：剥离 cloze 标记，只保留文本
                line = re.sub(r"\{\{c\d+::(.*?)\}\}", r"\1", line)
                out_lines.append(line)
        s = "\n".join(out_lines)
        # 清理“一句话总结”标题行（保留正文）
        s = re.sub(r"(?mi)^\s*###\s*\d*\.?\s*(One-Sentence Summary|一句话总结)\s*\n", "", s)
        # 去除 Anki 段落中的列表前缀
        lines = s.splitlines()
        out_lines = []
        in_anki = False
        inserted_blank_after_anki = False
        for line in lines:
            if re.match(r"^\s*##\s*🧠\s*Anki\s*卡片\s*$", line) or re.match(r"^\s*##\s*Anki\s*卡片\s*$", line):
                in_anki = True
                inserted_blank_after_anki = False
                out_lines.append(line)
                continue
            if in_anki:
                # 确保标题后第一行为空行
                if not inserted_blank_after_anki:
                    if line.strip() != "":
                        out_lines.append("")
                    inserted_blank_after_anki = True
                if re.match(r"^\s*##\s+", line):
                    in_anki = False
                    out_lines.append(line)
                    continue
                out_lines.append(re.sub(r"^\s*-\s+", "", line))
            else:
                out_lines.append(line)
        return "\n".join(out_lines)

    def _extract_anki_bounds(self, text: str) -> Optional[Dict[str, int]]:
        lines = text.splitlines()
        header_idx = None
        for i, line in enumerate(lines):
            if re.match(r"^\s*##\s*🧠\s*Anki\s*卡片\s*$", line) or re.match(r"^\s*##\s*Anki\s*卡片\s*$", line):
                header_idx = i
                break
        if header_idx is None:
            return None
        # body 从 header 下一行开始，直到下一个二级标题或文件末尾
        body_start = header_idx + 1
        # 跳过紧随其后的空行仅用于检测，不影响后续空行校正
        body_end = len(lines)
        for j in range(body_start, len(lines)):
            if re.match(r"^\s*##\s+", lines[j]):
                body_end = j
                break
        return {"header": header_idx, "start": body_start, "end": body_end}

    def _needs_cloze(self, anki_text: str) -> bool:
        has_any = False
        for raw in anki_text.splitlines():
            line = raw.strip()
            if not line:
                continue
            has_any = True
            if re.search(r"\{\{c\d+::.*?\}\}", line):
                return False
        # 有内容但没有任何 cloze
        return has_any

    def _second_pass_fix_anki_via_llm(self, anki_text: str) -> Optional[str]:
        # 已禁用
        return None

    def _maybe_fix_anki_cloze_via_llm(self, note_md: str) -> str:
        # 已禁用
        return note_md

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


