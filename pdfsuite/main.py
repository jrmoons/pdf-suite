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


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Suite")
    install_french(app)
    win = MainWindow()
    win.show()
    if len(sys.argv) > 1:
        win.open_file(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
