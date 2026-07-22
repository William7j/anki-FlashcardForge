from flashforge.prompts import PromptManager


def test_default_prompt_inserts_material() -> None:
    prompt = PromptManager().render("DNA 是遗传物质。")

    assert "DNA 是遗传物质。" in prompt
    assert "{{学习材料}}" not in prompt
    assert '"cards"' in prompt
    assert "输出前自检" in prompt
    assert "易混淆卡片" in prompt


def test_default_prompt_can_enable_image_instructions() -> None:
    prompt = PromptManager().render("以截图为准", image_mode=True)

    assert "截图" in prompt


def test_default_prompt_can_enable_document_extraction_rules() -> None:
    prompt = PromptManager().render("课堂内容", document_mode=True)

    assert "本地资料提炼规则" in prompt
    assert "学生回答和教师的中间尝试都不能直接视为事实" in prompt
    assert "课堂内容" in prompt


def test_user_override_is_loaded_and_can_be_removed(tmp_path) -> None:
    manager = PromptManager(user_prompt_dir=tmp_path)
    template = "# 自定义\n\n{{学习材料}}"

    manager.save_override("custom_mode", template)

    assert "custom_mode" in manager.available_names()
    assert manager.load("custom_mode") == template
    assert manager.remove_override("custom_mode") is True
    assert manager.remove_override("custom_mode") is False


def test_can_distinguish_built_in_and_custom_templates(tmp_path) -> None:
    manager = PromptManager(user_prompt_dir=tmp_path)
    manager.save_override("custom_mode", "# 自定义\n\n{{学习材料}}")

    assert manager.is_built_in("default_adaptive") is True
    assert manager.is_built_in("custom_mode") is False
