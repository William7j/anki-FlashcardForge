# FlashForge

FlashForge 是一个开源的 AI Anki 制卡桌面工具。它将文本或截图转换为可编辑的 Anki 卡片，再通过 AnkiConnect 导入本地牌组。

## 当前能力

- PySide6 桌面界面：文本输入、卡片预览、设置页；可自定义截图快捷键、截图后自动生成、生成后自动导入 Anki
- 本地 Markdown 资料导入：解析 YAML 元数据和课堂对话，清除角色动作描写并保留公式与纠错上下文
- OpenAI SDK 封装：支持自定义 `base_url`、模型和 API 密钥，以及 Ollama 本地模式
- `mss` 全局截图热键（默认 `Ctrl+Alt+A`，可在设置中修改）与多显示器选区，支持多模态直传或可选的本地 RapidOCR 文字降级
- 将模型 JSON 严格解析为 QA、Cloze、判断、单选、多选五类卡片
- AnkiConnect：可刷新、选择或手动输入目标牌组；自动创建牌组、注册 FlashForge 笔记类型，重试时跳过已存在卡片
- 单张编辑、删除和带反馈的重新生成
- 四套内置提示词，支持语法高亮、自动保存与用户覆盖版本
- 夜间模式、Anki 原生 MathJax、代码块渲染与 highlight.js 增强

## 模型建议

作者当前使用 Claude Sonnet 5 进行测试。处理截图、公式、表格或课堂板书时，推荐使用支持视觉输入的多模态大模型；纯文本模型只适合粘贴文本或使用 OCR 模式。

如果所在网络或账号需要 API 中转，可以尝试 [云雾 API 中转站](https://yunwu.ai/register?aff=5qjp7u)。这是第三方服务，请自行确认服务条款、隐私政策和 API Key 的安全性。

## 使用流程

1. 打开 Anki，并安装、启用 AnkiConnect 插件。
2. 启动 FlashForge，在“设置”中选择模型提供方并填写模型配置。
3. 在“制卡”页粘贴材料、导入本地 Markdown，或按已配置的快捷键截取材料区域；点击“生成卡片”。Markdown 课堂记录会启用专用提炼规则。
4. 在预览区选中卡片，可以编辑、删除或要求模型重新生成一张。
5. 选择目标牌组，点击“导入 Anki”。状态栏会显示逐张进度；重复导入会跳过已有卡片。

`Ollama（本地）` 使用 `http://127.0.0.1:11434/v1`，不需要 API Key。请确保选择的本地模型支持所选输入模式；视觉截图需要视觉模型，OCR 模式只需要文本模型。

API Key 会保存到 Windows Credential Manager；`%APPDATA%\FlashForge\settings.yaml` 只保存模型、牌组、主题和提示词等非敏感设置。已有 YAML 配置中的 Key 会在下次保存设置时自动迁移。

## 开发运行

需要 Python 3.12 或更高版本，并在 Anki 中安装并启动 AnkiConnect 插件。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .[dev]
python -m flashforge
```

需要离线 OCR 时额外安装：

```powershell
python -m pip install -e .[ocr]
```

RapidOCR 当前上游仅支持 Python 3.12；Python 3.13 及更高版本仍可使用文本、多模态和 Ollama 路径，但 OCR 模式不可用。

## 测试

```powershell
python -m pytest
```

## Windows 打包

```powershell
python -m pip install -e .[build]
.\scripts\build.ps1 -Clean
```

可执行文件将生成在 `dist\FlashForge\FlashForge.exe`。
若要将 RapidOCR 一并打入安装包，请在 Python 3.12 环境执行 `python -m pip install -e .[build,ocr]` 后再构建。

本地资料制卡的后续开发安排见 [DOCUMENT_CARD_PLAN.md](DOCUMENT_CARD_PLAN.md)。

## 许可证

本项目采用 [GNU AGPLv3](https://www.gnu.org/licenses/agpl-3.0.html) 或更高版本发布。
