# audionote-processor

将课程音频→转录稿→结构化 Obsidian 课堂纪要的半自动化工具。

- 课程匹配：基于 `.ics` 日历，优先命中时间区间内的课程；否则匹配到最近的开始/结束边界（≤1小时）。
- LLM “填空题”模式：程序预填 `course/date/week/sequence/transcript_file/status`，仅让 LLM 生成 `topic/tags/aliases` 与正文。
- Obsidian 集成：
  - 纪要保存到 `OBSIDIAN_VAULT_PATH/<课程名>/` 根目录。
  - 转录副本保存到 `OBSIDIAN_VAULT_PATH/<课程名>/Transcripts/`。
  - 文件命名：`{序号}-W{周次}-{课程名}.md` 与 `{序号}-W{周次}-{课程名}-Transcript.md`。
- 健壮性：
  - 失败即终止（LLM/保存/归档出错会 `FATAL` 并退出）。
  - 统一分割线为 `---`；自动修正 Anki `{{c1::...}}` 格式与列表项。
  - Debug 日志可开关。

## 快速开始

1) 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2) 准备 `.env`

```ini
# [PATHS]
AUDIO_DIR = "/Users/justin/Music/课程录制"
TRANSCRIPT_DIR = "/Users/justin/Music/课程录制/转录稿"
PROCESSED_TRANSCRIPT_DIR = "/Users/justin/Music/课程录制/转录稿/已处理"
OBSIDIAN_VAULT_PATH = "/Users/justin/Library/Mobile Documents/iCloud~md~obsidian/Documents/Cloud Vault"
ICS_FILE_PATH = "./schedule.ics"
LOG_FILE_PATH = "./processor.log"

# [SETTINGS]
ENABLE_AUTO_RENAME = true
SEMESTER_START_DATE = "2025-09-15"
CLINICAL_COURSES = "内科护理学,外科护理学,精神科护理学,妇产科护理学,儿科护理学"
LOG_LEVEL = "INFO"  # 或 DEBUG

# [LLM]
LLM_API_BASE = "https://api.openai.com/v1"      # 或兼容 OpenAI 的网关
LLM_API_TOKEN = ""                               # 在本机填写，不要入库
LLM_MODEL_NAME = "gpt-4o-mini"
LLM_MAX_TOKENS = 20000
LLM_RETRY_COUNT = 3
LLM_RETRY_DELAY = 5
```

放置 `schedule.ics` 于项目根目录（优先使用根目录的 `schedule.ics`）。

3) 一键运行

```bash
./run_processor.sh               # 普通运行
LOG_LEVEL=DEBUG ./run_processor.sh  # 开启调试日志
```

- 待处理 `.txt` 转录稿放入 `TRANSCRIPT_DIR`。
- 处理成功后，源 `.txt` 将移动到 `PROCESSED_TRANSCRIPT_DIR`。
- 纪要与转录副本写入 Obsidian Vault 指定目录。

4) 音频自动重命名（可选）

临时后台运行：
```bash
nohup .venv/bin/python file_monitor.py > monitor.out 2> monitor.err &
```
如需开机自启，建议使用 macOS `launchd`（参见 `file_monitor.py` 说明）。

## 工作原理

- 文件名时间戳锚定：`YYYYMMDD-HHMMSS-...`。
- 课程匹配：
  1) 若目标时间处于课程事件区间 `[begin, end]`，直接命中。
  2) 否则比较到开始/结束最近边界，≤1小时命中。
- LLM 生成：
  - 模板在 `prompts/`，采用“填空题”模式，仅需生成 `topic/tags/aliases` 和正文。
  - 生成后自动后处理：
    - 删除“一句话总结”标题行，仅保留引言与 `---` 分割线。
    - `***` 统一为 `---`。
    - 修正 `{{c1::...}}` 语法并移除 Anki 段落中的列表前缀。

## 日志与故障排查

- 日志文件：`processor.log`（路径由 `.env` 指定）。
- 控制台与文件同时输出。
- 设为 `LOG_LEVEL=DEBUG` 可查看匹配、模板选择、重试等细节。

## 目录结构（要点）

```
/audionote-processor
  ├─ modules/                 # 业务模块
  ├─ prompts/                 # Prompt 模板
  ├─ transcripts/             # 待处理转录稿（外部目录亦可）
  ├─ run_processor.sh         # 一键脚本
  ├─ schedule.ics             # 课表（示例/自备）
  ├─ .env                     # 本机配置（已在 .gitignore）
  └─ processor.log            # 运行日志
```

## 安全与建议

- 切勿将 `.env` 与 API Token 入库（已在 `.gitignore`）。
- 若使用第三方网关，请确保兼容 OpenAI Chat Completions 协议；不兼容可在 `LLMHandler` 中适配。

## 许可证

见 `LICENSE`（MIT）。
