"""Render a local visual preview of the FlashForge Anki card family."""

from __future__ import annotations

from pathlib import Path
import re
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from flashforge.anki import BASE_CSS, _answer_block, _card_shell, _remark_block  # noqa: E402


def _without_scripts(fragment: str) -> str:
    return re.sub(r"<script>[\s\S]*?</script>", "", fragment)


def _sample_remark(text: str) -> str:
    return (
        _remark_block()
        .replace("{{#Remark}}", "")
        .replace("{{Remark}}", text)
        .replace("{{/Remark}}", "")
    )


def render_preview(path: Path) -> None:
    cards = [
        _card_shell(
            "qa",
            "问答 / 答案",
            '<div class="ff-prompt">边界对齐为什么能提高内存访问效率？</div>'
            + _answer_block("它让一个数据尽量落在单个存储字内，减少跨边界读取次数。")
            + _sample_remark("区分“方便找地址”和“减少访存次数”。"),
        ),
        _card_shell(
            "cloze",
            "填空 / 答案",
            '<div class="ff-content">每一步的后验，会成为下一步计算的 <b>新先验</b>。</div>'
            + _sample_remark("复检中的贝叶斯更新可以连续迭代。"),
        ),
        _card_shell(
            "judge",
            "判断",
            '<div class="ff-prompt">互斥事件一定相互独立。</div>'
            '<div class="judge-buttons"><button class="option-button">正确</button>'
            '<button class="option-button">错误</button></div>',
        ),
        _card_shell(
            "choice",
            "单项选择",
            '<div class="ff-prompt">有放回抽样 5 次，恰有 2 次成功应使用哪种分布？</div>'
            '<div class="option-list"><button class="option-button">A. 超几何分布</button>'
            '<button class="option-button">B. 二项分布</button>'
            '<button class="option-button">C. 泊松分布</button>'
            '<button class="option-button">D. 均匀分布</button></div>',
        ),
        _card_shell(
            "multichoice",
            "多项选择",
            '<div class="ff-prompt">下列哪些因素属于可靠的课堂薄弱点证据？</div>'
            '<div class="option-list"><button class="option-button selected">A. 主动追问</button>'
            '<button class="option-button selected">B. 提示后纠正</button>'
            '<button class="option-button">C. 教材页码较大</button></div>'
            '<button class="answer-button">核对答案</button>',
        ),
    ]
    body = "\n".join(_without_scripts(card) for card in cards)
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FlashForge Anki Card Preview</title>
<style>{BASE_CSS}
.ff-shell {{ margin-bottom: 24px; }}
</style>
</head>
<body class="card">{body}</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    output = PROJECT_ROOT / "build" / "flashforge-anki-preview.html"
    render_preview(output)
    print(output)
