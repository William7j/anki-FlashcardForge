import sys

import pytest

from flashforge.ocr import LocalOcr, OcrError


def test_ocr_reports_python_version_requirement_on_newer_runtime() -> None:
    if sys.version_info < (3, 13):
        pytest.skip("当前运行时可以安装 RapidOCR。")

    with pytest.raises(OcrError, match="Python 3.12"):
        LocalOcr()


def test_ocr_extracts_text_from_rapidocr_style_result(tmp_path) -> None:
    class FakeEngine:
        def __call__(self, path):
            return (
                [
                    ([[0, 0], [1, 0], [1, 1], [0, 1]], "第一行", 0.99),
                    ([[0, 1], [1, 1], [1, 2], [0, 2]], "第二行", 0.98),
                ],
                0.01,
            )

    assert LocalOcr(FakeEngine()).extract(tmp_path / "source.png") == "第一行\n第二行"
