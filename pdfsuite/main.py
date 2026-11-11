import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def install_french(app):
    """Standard Qt texts in French (OK / Annuler / Oui / Non, colour and
    file dialogs...)."""
    from PySide6.QtCore import QTranslator, QLibraryInfo, QLocale
    QLocale.setDefault(QLocale(QLocale.French, QLocale.France))
    import os
    import PySide6
    tr = QTranslator(app)
    for folder in (QLibraryInfo.path(QLibraryInfo.TranslationsPath),
                   os.path.join(os.path.dirname(PySide6.__file__), "translations")):
        if tr.load("qtbase_fr", folder):
            app.installTranslator(tr)
            app._fr_translator = tr
            break


def app_icon():
    """Logo of the application (window, taskbar)."""
    import os
    from PySide6.QtGui import QIcon
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("logo.ico", "logo.png"):
        path = os.path.join(here, name)
        if os.path.exists(path):
            return QIcon(path)
    return QIcon()


def main():
    if sys.platform == "win32":
        try:   # own taskbar icon, not the Python one
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PDFSuite.App")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Suite")
    app.setWindowIcon(app_icon())
    install_french(app)
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1:
        win.open_file(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
