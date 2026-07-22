from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from flashforge.resources import app_icon_path


def test_packaged_application_icon_is_loadable() -> None:
    QApplication.instance() or QApplication([])
    icon_path = app_icon_path()

    assert icon_path.is_file()
    assert not QIcon(str(icon_path)).isNull()
