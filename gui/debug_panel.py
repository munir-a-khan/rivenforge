from PyQt5.QtWidgets import QTextEdit, QVBoxLayout, QWidget


class DebugPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlaceholderText("Run a screenshot analysis to see OCR, parser, and rule traces.")
        layout.addWidget(self._text)

    def set_debug_text(self, text: str):
        self._text.setPlainText(text)
