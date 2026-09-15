from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSettings, QSize
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QHBoxLayout, QSplitter,
    QToolBar, QFileDialog, QMessageBox, QInputDialog, QLabel, QSpinBox, QDialog,
    QColorDialog, QLineEdit, QToolButton, QStyle,
)

from .pdf_document import PdfDocument
from .page_view import PdfGraphicsView
from .thumbnail_panel import ThumbnailPanel
from .tools import Tool
from .dialogs import (
    ask_password, ask_page_ranges, TextEditDialog, SignatureDialog,
)
from . import theme as theme_mod
from .icons import make_icon


class DocumentTab(QWidget):
    def __init__(self, pdf_document: PdfDocument, parent=None):
        super().__init__(parent)
        self.pdf_document = pdf_document

        self.view = PdfGraphicsView(pdf_document)
        self.thumbnails = ThumbnailPanel()
        self.thumbnails.rebuild(pdf_document)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.thumbnails)
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([160, 800])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.thumbnails.pageActivated.connect(self.view.goto_page)

    @property
    def file_path(self) -> str | None:
        return self.pdf_document.path

    @property
    def dirty(self) -> bool:
        return self.pdf_document.dirty


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Suite")
        self.resize(1280, 860)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        self._current_tool = Tool.SELECT
        self._current_color = (0.9, 0.1, 0.1)
        self._signature_png: bytes | None = None
        self._tab_views: list[PdfGraphicsView] = []

        self.settings = QSettings("PDFSuite", "PDFSuite")
        self._dark = bool(self.settings.value("dark_theme", False, type=bool))

        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._update_actions_enabled()
        self._apply_theme()

    # -- icon helpers -------------------------------------------------
    def _icon(self, kind: str, accent: bool = False):
        color = theme_mod.icon_color(self._dark)
        if accent:
            return make_icon(kind, color, QColor.fromRgbF(*self._current_color))
        return make_icon(kind, color)

    def _set_icon(self, action: QAction, kind: str, accent: bool = False):
        action.setIcon(self._icon(kind, accent))
        self._action_icons[action] = (kind, accent)

    def _apply_icons(self):
        for action, (kind, accent) in self._action_icons.items():
            action.setIcon(self._icon(kind, accent))
        self._update_theme_action()

    # -- ui construction -------------------------------------------------
    def _build_menu(self):
        self._action_icons: dict[QAction, tuple[str, bool]] = {}
        m = self.menuBar()

        file_menu = m.addMenu("&Fichier")
        self.act_open = QAction("Ouvrir...", self, shortcut=QKeySequence.Open,
                                 triggered=self.open_file)
        self.act_save = QAction("Enregistrer", self, shortcut=QKeySequence.Save,
                                 triggered=lambda: self.save_current(False))
        self.act_save_as = QAction("Enregistrer sous...", self,
                                    shortcut=QKeySequence.SaveAs,
                                    triggered=lambda: self.save_current(True))
        self.act_close_tab = QAction("Fermer l'onglet", self, shortcut=QKeySequence.Close,
                                      triggered=lambda: self.close_tab(self.tabs.currentIndex()))
        self._set_icon(self.act_open, "open")
        self._set_icon(self.act_save, "save")
        self._set_icon(self.act_save_as, "save")
        for a in (self.act_open, self.act_save, self.act_save_as, self.act_close_tab):
            file_menu.addAction(a)
        file_menu.addSeparator()
        file_menu.addAction(QAction("Quitter", self, triggered=self.close))

        page_menu = m.addMenu("&Pages")
        self.act_insert_blank = QAction("Insérer une page vierge", self,
                                         triggered=self.insert_blank_page)
        self.act_delete_pages = QAction("Supprimer la sélection", self,
                                         triggered=self.delete_selected_pages)
        self.act_rotate_left = QAction("Rotation -90°", self,
                                        triggered=lambda: self.rotate_selected(-90))
        self.act_rotate_right = QAction("Rotation +90°", self,
                                         triggered=lambda: self.rotate_selected(90))
        self.act_insert_pdf = QAction("Insérer un PDF...", self,
                                       triggered=self.insert_pdf)
        self.act_extract = QAction("Extraire des pages...", self,
                                    triggered=self.extract_pages)
        self.act_split = QAction("Diviser le document...", self,
                                  triggered=self.split_document)
        self._set_icon(self.act_insert_blank, "insertblank")
        self._set_icon(self.act_delete_pages, "deletepages")
        self._set_icon(self.act_rotate_left, "rotateleft")
        self._set_icon(self.act_rotate_right, "rotateright")
        self._set_icon(self.act_insert_pdf, "insertpdf")
        self._set_icon(self.act_extract, "extract")
        self._set_icon(self.act_split, "split")
        for a in (self.act_insert_blank, self.act_delete_pages, self.act_rotate_left,
                  self.act_rotate_right, self.act_insert_pdf, self.act_extract, self.act_split):
            page_menu.addAction(a)

        security_menu = m.addMenu("&Sécurité")
        self.act_set_password = QAction("Ajouter un mot de passe...", self,
                                         triggered=self.set_password)
        self._set_icon(self.act_set_password, "password")
        security_menu.addAction(self.act_set_password)

        view_menu = m.addMenu("&Affichage")
        self.act_zoom_in = QAction("Zoom avant", self, shortcut=QKeySequence.ZoomIn,
                                    triggered=lambda: self.zoom_by(1.15))
        self.act_zoom_out = QAction("Zoom arrière", self, shortcut=QKeySequence.ZoomOut,
                                     triggered=lambda: self.zoom_by(1 / 1.15))
        self.act_zoom_100 = QAction("Zoom 100%", self, triggered=lambda: self.zoom_to(1.33))
        self._set_icon(self.act_zoom_in, "zoomin")
        self._set_icon(self.act_zoom_out, "zoomout")
        for a in (self.act_zoom_in, self.act_zoom_out, self.act_zoom_100):
            view_menu.addAction(a)
        view_menu.addSeparator()
        self.act_toggle_theme = QAction("Thème sombre", self, checkable=True,
                                         checked=self._dark, triggered=self.toggle_theme)
        view_menu.addAction(self.act_toggle_theme)

    def _tool_action(self, text: str, tool: Tool, group: QActionGroup) -> QAction:
        act = QAction(text, self, checkable=True)
        act.triggered.connect(lambda checked, t=tool: self._select_tool(t))
        group.addAction(act)
        return act

    TOOL_ICONS = {
        Tool.PAN: ("pan", False),
        Tool.SELECT: ("select", False),
        Tool.HIGHLIGHT: ("highlight", True),
        Tool.UNDERLINE: ("underline", True),
        Tool.STRIKEOUT: ("strikeout", True),
        Tool.FREETEXT: ("freetext", True),
        Tool.NOTE: ("note", False),
        Tool.INK: ("ink", True),
        Tool.RECT: ("rect", True),
        Tool.ELLIPSE: ("ellipse", True),
        Tool.LINE: ("line", True),
        Tool.ERASER: ("eraser", False),
        Tool.TEXTEDIT: ("textedit", False),
        Tool.SIGNATURE: ("signature", False),
        Tool.MEASURE_LINE: ("measure_line", False),
        Tool.MEASURE_PERIMETER: ("measure_perimeter", False),
    }

    def _build_toolbar(self):
        tb = QToolBar("Principal")
        tb.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tb.setIconSize(QSize(22, 22))
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addAction(self.act_open)
        tb.addAction(self.act_save)
        tb.addSeparator()

        group = QActionGroup(self)
        group.setExclusive(True)
        tool_defs = [
            ("Sélectionner", Tool.SELECT),
            ("Main", Tool.PAN),
            ("Surligner", Tool.HIGHLIGHT),
            ("Souligner", Tool.UNDERLINE),
            ("Barrer", Tool.STRIKEOUT),
            ("Texte libre", Tool.FREETEXT),
            ("Note", Tool.NOTE),
            ("Dessin", Tool.INK),
            ("Rectangle", Tool.RECT),
            ("Ellipse", Tool.ELLIPSE),
            ("Ligne", Tool.LINE),
            ("Gomme", Tool.ERASER),
            ("Modifier texte", Tool.TEXTEDIT),
            ("Signature", Tool.SIGNATURE),
        ]
        self._tool_actions = {}
        for text, tool in tool_defs:
            act = self._tool_action(text, tool, group)
            kind, accent = self.TOOL_ICONS[tool]
            self._set_icon(act, kind, accent)
            if tool == Tool.SELECT:
                act.setChecked(True)
            self._tool_actions[tool] = act
            tb.addAction(act)

        tb.addSeparator()
        measure_defs = [
            ("Mesurer une ligne", Tool.MEASURE_LINE),
            ("Périmètre", Tool.MEASURE_PERIMETER),
        ]
        for text, tool in measure_defs:
            act = self._tool_action(text, tool, group)
            kind, accent = self.TOOL_ICONS[tool]
            self._set_icon(act, kind, accent)
            self._tool_actions[tool] = act
            tb.addAction(act)
        self.act_reset_scale = QAction("Réinitialiser l'échelle", self,
                                        triggered=self.reset_scale)
        tb.addAction(self.act_reset_scale)

        tb.addSeparator()
        self.act_color = QAction("Couleur", self, triggered=self.pick_color)
        self._set_icon(self.act_color, "color", accent=True)
        tb.addAction(self.act_color)

        self.act_new_signature = QAction("Nouvelle signature", self, triggered=self.new_signature)
        self._set_icon(self.act_new_signature, "signature")
        tb.addAction(self.act_new_signature)

        tb.addSeparator()
        self.act_form_mode = QAction("Formulaire", self, checkable=True,
                                      triggered=self.toggle_form_mode)
        self._set_icon(self.act_form_mode, "form")
        tb.addAction(self.act_form_mode)

        tb.addSeparator()
        tb.addAction(self.act_insert_blank)
        tb.addAction(self.act_delete_pages)
        tb.addAction(self.act_rotate_left)
        tb.addAction(self.act_rotate_right)

        tb.addSeparator()
        tb.addAction(self.act_zoom_out)
        tb.addAction(self.act_zoom_in)

        tb.addSeparator()
        self.act_toggle_theme_tb = QAction("Thème", self, triggered=self.toggle_theme)
        tb.addAction(self.act_toggle_theme_tb)
        self._update_theme_action()

    def _build_statusbar(self):
        sb = self.statusBar()
        self.page_label = QLabel("Page — / —")
        self.zoom_label = QLabel("100%")
        sb.addPermanentWidget(self.page_label)
        sb.addPermanentWidget(self.zoom_label)

    def _update_actions_enabled(self):
        has_doc = self.current_tab() is not None
        for a in (self.act_save, self.act_save_as, self.act_close_tab,
                  self.act_insert_blank, self.act_delete_pages, self.act_rotate_left,
                  self.act_rotate_right, self.act_insert_pdf, self.act_extract,
                  self.act_split, self.act_set_password, self.act_zoom_in,
                  self.act_zoom_out, self.act_zoom_100, self.act_form_mode,
                  self.act_color, self.act_new_signature, self.act_reset_scale):
            a.setEnabled(has_doc)
        for act in self._tool_actions.values():
            act.setEnabled(has_doc)

    # -- theme ----------------------------------------------------------
    def _update_theme_action(self):
        kind = "theme_light" if self._dark else "theme_dark"
        label = "Thème clair" if self._dark else "Thème sombre"
        self.act_toggle_theme_tb.setIcon(self._icon(kind))
        self.act_toggle_theme_tb.setText(label)
        self.act_toggle_theme.blockSignals(True)
        self.act_toggle_theme.setChecked(self._dark)
        self.act_toggle_theme.blockSignals(False)

    def toggle_theme(self):
        self.set_theme(not self._dark)

    def set_theme(self, dark: bool):
        self._dark = dark
        self.settings.setValue("dark_theme", dark)
        self._apply_theme()

    def _apply_theme(self):
        app = QApplication.instance()
        theme_mod.apply_theme(app, self._dark)
        surround = theme_mod.surround_color(self._dark)
        for i in range(self.tabs.count()):
            tab = self.tabs.widget(i)
            tab.view.apply_theme(surround)
        self._apply_icons()

    # -- tab helpers ------------------------------------------------------
    def current_tab(self) -> DocumentTab | None:
        return self.tabs.currentWidget()

    def _on_tab_changed(self, _index):
        tab = self.current_tab()
        if tab is not None:
            tab.view.set_tool(self._current_tool)
            tab.view.set_color(self._current_color)
            tab.view.pageChanged.connect(self._update_page_label, Qt.UniqueConnection)
            self._update_page_label(tab.view.current_page())
            self.zoom_label.setText(f"{int(tab.view.zoom / 1.33 * 100)}%")
        self._update_actions_enabled()

    def _update_page_label(self, page_no: int):
        tab = self.current_tab()
        if tab is None:
            return
        self.page_label.setText(f"Page {page_no + 1} / {tab.pdf_document.page_count}")

    # -- file operations ----------------------------------------------
    def open_file(self, path: str | None = None):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Ouvrir un PDF", "", "PDF (*.pdf)")
            if not path:
                return
        password = None
        while True:
            try:
                doc = PdfDocument(path, password=password)
                break
            except PermissionError:
                password = ask_password(self, os.path.basename(path))
                if password is None:
                    return
            except Exception as exc:
                QMessageBox.critical(self, "Erreur", f"Impossible d'ouvrir le fichier :\n{exc}")
                return

        tab = DocumentTab(doc)
        tab.view.apply_theme(theme_mod.surround_color(self._dark))
        tab.view.set_color(self._current_color)
        tab.view.documentModified.connect(lambda: self._on_doc_modified(tab))
        tab.view.requestTextEdit.connect(
            lambda pno, bbox, text, size: self._on_text_edit_requested(tab, pno, bbox, text, size)
        )
        tab.view.requestSignaturePlacement.connect(
            lambda pno, pt: self._on_signature_requested(tab, pno, pt)
        )
        tab.view.zoomChanged.connect(lambda z, t=tab: self._on_zoom_changed(t, z))
        tab.thumbnails.deletePagesRequested.connect(
            lambda pages: self._delete_pages(tab, pages)
        )
        tab.thumbnails.pagesReordered.connect(
            lambda order: self._reorder_pages(tab, order)
        )
        index = self.tabs.addTab(tab, os.path.basename(path))
        self.tabs.setCurrentIndex(index)

    def _on_zoom_changed(self, tab: DocumentTab, zoom: float):
        if self.current_tab() is tab:
            self.zoom_label.setText(f"{int(zoom / 1.33 * 100)}%")

    def _on_doc_modified(self, tab: DocumentTab):
        idx = self.tabs.indexOf(tab)
        title = os.path.basename(tab.file_path or "Sans titre")
        if not title.endswith("*"):
            self.tabs.setTabText(idx, title + " *")

    def save_current(self, save_as: bool):
        tab = self.current_tab()
        if tab is None:
            return
        path = tab.file_path
        if save_as or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Enregistrer sous", path or "document.pdf", "PDF (*.pdf)"
            )
            if not path:
                return
        try:
            if getattr(tab.pdf_document, "_pending_encrypt", None):
                tab.pdf_document.save_with_pending_encryption(path)
            else:
                tab.pdf_document.save(path)
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Échec de l'enregistrement :\n{exc}")
            return
        idx = self.tabs.indexOf(tab)
        self.tabs.setTabText(idx, os.path.basename(path))

    def close_tab(self, index: int):
        tab = self.tabs.widget(index)
        if tab is None:
            return
        if tab.dirty:
            resp = QMessageBox.question(
                self, "Modifications non enregistrées",
                "Enregistrer les modifications avant de fermer ?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            )
            if resp == QMessageBox.Cancel:
                return
            if resp == QMessageBox.Save:
                self.tabs.setCurrentIndex(index)
                self.save_current(False)
                if tab.dirty:
                    return
        tab.pdf_document.close()
        self.tabs.removeTab(index)

    # -- tools ------------------------------------------------------------
    def _select_tool(self, tool: Tool):
        self._current_tool = tool
        tab = self.current_tab()
        if tab is not None:
            tab.view.set_tool(tool)

    def pick_color(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self._current_color), self, "Couleur")
        if c.isValid():
            self._current_color = (c.redF(), c.greenF(), c.blueF())
            tab = self.current_tab()
            if tab is not None:
                tab.view.set_color(self._current_color)
            self._apply_icons()

    def reset_scale(self):
        tab = self.current_tab()
        if tab is None:
            return
        tab.pdf_document.scale_points_per_meter = None
        QMessageBox.information(
            self, "Échelle réinitialisée",
            "La prochaine mesure (ligne ou périmètre) vous demandera à\n"
            "nouveau l'échelle réelle du plan."
        )

    def new_signature(self):
        dlg = SignatureDialog(self)
        if dlg.exec() == QDialog.Accepted and not dlg.canvas.is_empty():
            self._signature_png = dlg.png_bytes()
            self._tool_actions[Tool.SIGNATURE].setChecked(True)
            self._select_tool(Tool.SIGNATURE)

    def toggle_form_mode(self, checked: bool):
        tab = self.current_tab()
        if tab is not None:
            tab.view.set_form_mode(checked)

    # -- zoom / navigation --------------------------------------------
    def zoom_by(self, factor: float):
        tab = self.current_tab()
        if tab is not None:
            self.zoom_to(tab.view.zoom * factor)

    def zoom_to(self, zoom: float):
        tab = self.current_tab()
        if tab is None:
            return
        tab.view.set_zoom(zoom)
        self.zoom_label.setText(f"{int(zoom / 1.33 * 100)}%")

    # -- page operations ----------------------------------------------
    def _refresh_thumbs(self, tab: DocumentTab):
        tab.thumbnails.rebuild(tab.pdf_document)
        tab.view.refresh_all()
        self._on_doc_modified(tab)

    def insert_blank_page(self):
        tab = self.current_tab()
        if tab is None:
            return
        pages = tab.thumbnails.selected_pages()
        at = pages[0] if pages else tab.pdf_document.page_count
        tab.pdf_document.insert_blank_page(at)
        self._refresh_thumbs(tab)

    def delete_selected_pages(self):
        tab = self.current_tab()
        if tab is None:
            return
        pages = tab.thumbnails.selected_pages()
        if pages:
            self._delete_pages(tab, pages)

    def _delete_pages(self, tab: DocumentTab, pages: list[int]):
        if tab.pdf_document.page_count - len(pages) < 1:
            QMessageBox.warning(self, "Action refusée", "Le document doit garder au moins une page.")
            return
        tab.pdf_document.delete_pages(pages)
        self._refresh_thumbs(tab)

    def _reorder_pages(self, tab: DocumentTab, new_order: list[int]):
        tab.pdf_document.reorder_pages(new_order)
        self._refresh_thumbs(tab)

    def rotate_selected(self, degrees: int):
        tab = self.current_tab()
        if tab is None:
            return
        pages = tab.thumbnails.selected_pages() or list(range(tab.pdf_document.page_count))
        for p in pages:
            tab.pdf_document.rotate_page(p, degrees)
        self._refresh_thumbs(tab)

    def insert_pdf(self):
        tab = self.current_tab()
        if tab is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Insérer un PDF", "", "PDF (*.pdf)")
        if not path:
            return
        max_pos = tab.pdf_document.page_count + 1
        pos, ok = QInputDialog.getInt(
            self, "Position d'insertion",
            f"Insérer avant la page (1 à {max_pos}) :",
            max_pos, 1, max_pos,
        )
        if not ok:
            return
        tab.pdf_document.insert_pdf(path, at_index=pos - 1)
        self._refresh_thumbs(tab)

    def extract_pages(self):
        tab = self.current_tab()
        if tab is None:
            return
        indices = ask_page_ranges(self, "Extraire des pages", tab.pdf_document.page_count)
        if not indices:
            return
        out_path, _ = QFileDialog.getSaveFileName(self, "Enregistrer l'extraction", "", "PDF (*.pdf)")
        if not out_path:
            return
        tab.pdf_document.extract_pages(indices, out_path)
        QMessageBox.information(self, "Terminé", f"{len(indices)} page(s) extraite(s) vers :\n{out_path}")

    def split_document(self):
        tab = self.current_tab()
        if tab is None:
            return
        total = tab.pdf_document.page_count
        n, ok = QInputDialog.getInt(
            self, "Diviser le document",
            "Nombre de pages par fichier :", 1, 1, total,
        )
        if not ok:
            return
        out_dir = QFileDialog.getExistingDirectory(self, "Dossier de sortie")
        if not out_dir:
            return
        ranges = []
        i = 0
        while i < total:
            ranges.append((i, min(i + n, total) - 1))
            i += n
        base = os.path.splitext(os.path.basename(tab.file_path or "document"))[0]
        paths = tab.pdf_document.split_at(out_dir, base, ranges)
        QMessageBox.information(self, "Terminé", f"{len(paths)} fichier(s) créé(s) dans :\n{out_dir}")

    def set_password(self):
        tab = self.current_tab()
        if tab is None:
            return
        pw, ok = QInputDialog.getText(self, "Mot de passe", "Nouveau mot de passe :", QLineEdit.Password)
        if not ok or not pw:
            return
        confirm, ok = QInputDialog.getText(self, "Confirmation", "Confirmer le mot de passe :", QLineEdit.Password)
        if not ok or confirm != pw:
            QMessageBox.warning(self, "Erreur", "Les mots de passe ne correspondent pas.")
            return
        tab.pdf_document.set_password(pw)
        self._on_doc_modified(tab)
        QMessageBox.information(
            self, "Mot de passe défini",
            "Le mot de passe sera appliqué au prochain enregistrement (Ctrl+S)."
        )

    # -- interactive edits from the view -------------------------------
    def _on_text_edit_requested(self, tab: DocumentTab, page_no, bbox, text, fontsize):
        dlg = TextEditDialog(self, text, fontsize)
        if dlg.exec() == QDialog.Accepted:
            new_text, size = dlg.values()
            tab.view.apply_text_edit(page_no, bbox, new_text, size)
            self._on_doc_modified(tab)

    def _on_signature_requested(self, tab: DocumentTab, page_no, pt):
        if self._signature_png is None:
            dlg = SignatureDialog(self)
            if dlg.exec() != QDialog.Accepted or dlg.canvas.is_empty():
                return
            self._signature_png = dlg.png_bytes()
        tab.view.place_signature_image(page_no, pt, self._signature_png)
        self._on_doc_modified(tab)

    # -- close handling -----------------------------------------------
    def closeEvent(self, event):
        while self.tabs.count():
            before = self.tabs.count()
            self.close_tab(0)
            if self.tabs.count() == before:
                event.ignore()
                return
        event.accept()
