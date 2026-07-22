from flashforge.screenshot import GlobalScreenshotHotkey


class FakeKeyboard:
    def __init__(self) -> None:
        self.registered = []
        self.removed = []

    def add_hotkey(self, shortcut, callback):
        self.registered.append((shortcut, callback))
        return "hotkey-id"

    def remove_hotkey(self, hotkey_id):
        self.removed.append(hotkey_id)


def test_global_hotkey_registers_once_and_unregisters() -> None:
    keyboard = FakeKeyboard()
    callback = lambda: None
    hotkey = GlobalScreenshotHotkey("ctrl+alt+a", callback, keyboard)

    assert hotkey.register() is True
    assert hotkey.register() is True
    hotkey.unregister()

    assert keyboard.registered == [("ctrl+alt+a", callback)]
    assert keyboard.removed == ["hotkey-id"]
