"""Application settings (Windows registry). Tests set PDFSUITE_SETTINGS to
use a separate store and never touch the real user preferences."""
import os

from PySide6.QtCore import QSettings


def app_settings() -> QSettings:
    return QSettings("PDFSuite", os.environ.get("PDFSUITE_SETTINGS", "PDFSuite"))
