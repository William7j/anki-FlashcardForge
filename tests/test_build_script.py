from pathlib import Path


def test_build_script_collects_packaged_prompts() -> None:
    script = Path("scripts/build.ps1").read_text(encoding="utf-8")

    assert "PyInstaller" in script
    assert "--specpath build" in script
    assert "--icon" in script
    assert "--collect-data flashforge" in script
    assert "--exclude-module pytest" in script
    assert "$projectRoot\\src\\flashforge\\prompts;flashforge/prompts" in script
    assert "--clean" not in script
