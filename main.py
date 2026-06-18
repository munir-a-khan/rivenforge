"""
WF Riven Roller — entry point.

First-run behaviour:
  - If ChromaDB not yet built, prompts user to build it via Settings tab.
  - EasyOCR models download automatically on first use.
"""

import sys
import os

# Ensure project root is on path (needed when running as bundled exe)
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt

from gui.main_window import MainWindow


def main():
    # Enable HiDPI scaling
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("WF Riven Roller")
    app.setStyle("Fusion")

    # Dark palette
    from PyQt5.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window,          QColor(30, 30, 30))
    palette.setColor(QPalette.WindowText,      QColor(220, 220, 220))
    palette.setColor(QPalette.Base,            QColor(20, 20, 20))
    palette.setColor(QPalette.AlternateBase,   QColor(40, 40, 40))
    palette.setColor(QPalette.ToolTipBase,     QColor(255, 255, 220))
    palette.setColor(QPalette.ToolTipText,     QColor(0, 0, 0))
    palette.setColor(QPalette.Text,            QColor(220, 220, 220))
    palette.setColor(QPalette.Button,          QColor(50, 50, 50))
    palette.setColor(QPalette.ButtonText,      QColor(220, 220, 220))
    palette.setColor(QPalette.BrightText,      QColor(255, 80, 80))
    palette.setColor(QPalette.Link,            QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight,       QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
