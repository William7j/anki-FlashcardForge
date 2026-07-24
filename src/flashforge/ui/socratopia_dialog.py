"""Course and lesson selection for Socratopia imports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flashforge.socratopia import SocratopiaCourse, SocratopiaLesson


class SocratopiaLessonDialog(QDialog):
    """Select one concrete lesson after automatic Socratopia discovery."""

    def __init__(
        self,
        courses: Sequence[SocratopiaCourse],
        lessons_by_course: Mapping[str, Sequence[SocratopiaLesson]],
        *,
        connected: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._courses = list(courses)
        self._lessons_by_course = {
            key: list(lessons) for key, lessons in lessons_by_course.items()
        }
        self._visible_lessons: list[SocratopiaLesson] = []
        self.selected_course: SocratopiaCourse | None = None
        self.selected_lesson: SocratopiaLesson | None = None

        self.setWindowTitle("选择 Socratopia 课堂")
        self.setMinimumSize(820, 560)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        connection_text = (
            "已连接 Socratopia，本次将读取所选课堂对应的 qbook 原始教材。"
            if connected
            else "未检测到正在运行的 Socratopia；仍可选择课堂，但原始教材不可用时将使用课堂缓存。"
        )
        self.connection_status = QLabel(connection_text)
        self.connection_status.setWordWrap(True)
        if not connected:
            self.connection_status.setStyleSheet("color: #b45309;")
        layout.addWidget(self.connection_status)

        layout.addWidget(QLabel("课程"))
        self.course_input = QComboBox()
        for course in self._courses:
            count = len(self._lessons_by_course.get(course.key, []))
            self.course_input.addItem(f"{course.display_name} · {count} 堂课", course.key)
        self.course_input.currentIndexChanged.connect(self._refresh_lessons)
        layout.addWidget(self.course_input)

        layout.addWidget(QLabel("课堂记录"))
        self.lesson_table = QTableWidget(0, 5)
        self.lesson_table.setHorizontalHeaderLabels(
            ["时间", "课堂", "时长", "消息", "教学记录"]
        )
        self.lesson_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.lesson_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.lesson_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.lesson_table.verticalHeader().setVisible(False)
        header = self.lesson_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.lesson_table.itemSelectionChanged.connect(self._update_preview)
        self.lesson_table.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        layout.addWidget(self.lesson_table, stretch=1)

        layout.addWidget(QLabel("课堂摘要"))
        self.lesson_preview = QPlainTextEdit()
        self.lesson_preview.setReadOnly(True)
        self.lesson_preview.setMaximumHeight(120)
        layout.addWidget(self.lesson_preview)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("取消")
        self.use_button = buttons.addButton(
            "使用这堂课制卡", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.use_button.clicked.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._refresh_lessons()

    def _current_course(self) -> SocratopiaCourse | None:
        key = self.course_input.currentData()
        return next((course for course in self._courses if course.key == key), None)

    def _refresh_lessons(self) -> None:
        course = self._current_course()
        self._visible_lessons = (
            list(self._lessons_by_course.get(course.key, [])) if course is not None else []
        )
        self.lesson_table.setRowCount(len(self._visible_lessons))
        for row, lesson in enumerate(self._visible_lessons):
            values = [
                lesson.date_label,
                lesson.title,
                lesson.duration_label,
                str(lesson.message_count),
                "总结 + 课后效果"
                if lesson.summary and lesson.teaching_effect
                else "课堂总结"
                if lesson.summary
                else "课后效果"
                if lesson.teaching_effect
                else "课堂对话",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column in {0, 2, 3, 4}:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.lesson_table.setItem(row, column, item)
        if self._visible_lessons:
            self.lesson_table.selectRow(0)
            self.use_button.setEnabled(True)
        else:
            self.lesson_preview.setPlainText("这门课程暂无课堂记录。")
            self.use_button.setEnabled(False)

    def _selected_row(self) -> int:
        rows = self.lesson_table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _update_preview(self) -> None:
        row = self._selected_row()
        if 0 <= row < len(self._visible_lessons):
            self.lesson_preview.setPlainText(self._visible_lessons[row].record_preview)
        else:
            self.lesson_preview.clear()

    def _accept_selection(self) -> None:
        course = self._current_course()
        row = self._selected_row()
        if course is None or not (0 <= row < len(self._visible_lessons)):
            return
        self.selected_course = course
        self.selected_lesson = self._visible_lessons[row]
        self.accept()
