from __future__ import annotations

import os

from PySide6.QtCore import Qt, QSettings
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QHBoxLayout, QSplitter,
    QToolBar, QFileDialog, QMessageBox, QInputDialog, QLabel, QDialog,
    QColorDialog, QLineEdit, QComboBox, QProgressDialog, QSlider, QToolButton,
    QSpinBox,
)
import math

from .pdf_document import PdfDocument, STAMP_COLORS
from .page_view import PdfGraphicsView
from .thumbnail_panel import ThumbnailPanel
from .tools import Tool
from .dialogs import (
    ask_password, ask_page_ranges, TextEditDialog, SignatureDialog,
)
from .ribbon import Ribbon
from .settings import app_settings
from .measure_bar import MeasureBar
from .page_view import MEASURE_TOOLS
from . import theme as theme_mod
from .icons import make_icon

CUSTOM_STAMP = "Personnalisé…"


class DocumentTab(QWidget):
    def __init__(self, pdf_document: PdfDocument, parent=None):
        super().__init__(parent)
        self.pdf_document = pdf_document

        self.view = PdfGraphicsView(pdf_document)
        self.view2: PdfGraphicsView | None = None   # split view (idea 25)
        self.thumbnails = ThumbnailPanel()
        self.thumbnails.rebuild(pdf_document)

        self.view_splitter = QSplitter(Qt.Horizontal)
        self.view_splitter.addWidget(self.view)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.thumbnails)
        splitter.addWidget(self.view_splitter)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([160, 800])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.thumbnails.pageActivated.connect(self.view.goto_page)

    def views(self) -> list[PdfGraphicsView]:
        return [v for v in (self.view, self.view2) if v is not None]

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
        self.setAcceptDrops(True)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self.tabs)

        self._current_tool = Tool.SELECT
        self._current_color = (0.9, 0.1, 0.1)
        self._signature_png: bytes | None = None

        self.settings = app_settings()
        self._dark = bool(self.settings.value("dark_theme", False, type=bool))

        self._build_actions()
        self._build_menu()
        self._build_ribbon()
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

    def _act(self, text, slot=None, icon=None, accent=False, shortcut=None,
             checkable=False, tip=None, needs_doc=True) -> QAction:
        a = QAction(text, self, checkable=checkable)
        if slot is not None:
            a.triggered.connect(slot)
        if icon:
            self._set_icon(a, icon, accent)
        if shortcut is not None:
            a.setShortcut(shortcut)
        if tip:
            a.setToolTip(tip)
            a.setStatusTip(tip)
        # added to the window too, so shortcuts work whatever ribbon tab is shown
        self.addAction(a)
        if needs_doc:
            self._doc_actions.append(a)
        return a

    # -- actions --------------------------------------------------------
    TOOL_DEFS = {
        # tool: (label, icon, accent, tip)
        Tool.SELECT: ("Sélectionner", "select", False, "Sélectionner / déplacer les objets (Échap)"),
        Tool.PAN: ("Main", "pan", False, "Faire défiler la page à la souris"),
        Tool.HIGHLIGHT: ("Surligner", "highlight", True, None),
        Tool.UNDERLINE: ("Souligner", "underline", True, None),
        Tool.STRIKEOUT: ("Barrer", "strikeout", True, None),
        Tool.FREETEXT: ("Texte libre", "freetext", True, None),
        Tool.NOTE: ("Note", "note", False, None),
        Tool.INK: ("Dessin", "ink", True, None),
        Tool.RECT: ("Rectangle", "rect", True, None),
        Tool.ELLIPSE: ("Ellipse", "ellipse", True, None),
        Tool.LINE: ("Ligne", "line", True, None),
        Tool.ARROW: ("Flèche", "arrow", True, "Glisser du départ vers la pointe"),
        Tool.CLOUD: ("Nuage", "cloud", True, "Nuage de révision : glisser pour entourer la zone"),
        Tool.CALLOUT: ("Légende", "callout", True,
                       "Glisser du point visé vers l'endroit du texte"),
        Tool.STAMP: ("Tampon", "stamp", False, "Cliquer pour poser le tampon choisi (date + nom)"),
        Tool.ERASER: ("Gomme", "eraser", False, None),
        Tool.TEXTEDIT: ("Modifier texte", "textedit", False, None),
        Tool.SIGNATURE: ("Signature", "signature", False, None),
        Tool.ROOM: ("Pièce auto", "room", False,
                    "Cliquez dans une pièce : contour, périmètre, surface, cotes des murs "
                    "avec portes et fenêtres (plans exportés avec leurs calques)"),
        Tool.DIMENSION: ("Cote", "dimension", False,
                         "Clic A, clic B, puis déplacez pour décaler la cote et cliquez (Maj = angle droit)"),
        Tool.MEASURE_LINE: ("Longueur", "measure_line", False, "Mesurer une ligne"),
        Tool.MEASURE_PERIMETER: ("Périmètre", "measure_perimeter", False,
                                 "Clic à chaque coin, clic droit ou Entrée pour terminer"),
        Tool.MEASURE_AREA: ("Surface", "measure_area", False,
                            "Surface en m² : clic à chaque coin, clic droit ou Entrée pour terminer"),
        Tool.CAPTURE: ("Capture", "capture", False,
                       "Copier une zone (avec les cotes) dans le presse-papiers"),
    }

    def _build_actions(self):
        self._action_icons: dict[QAction, tuple[str, bool]] = {}
        self._doc_actions: list[QAction] = []

        # file
        self.act_open = self._act("Ouvrir", self.open_file, "open", shortcut=QKeySequence.Open,
                                  needs_doc=False)
        self.act_save = self._act("Enregistrer sous", self.save_current, "save",
                                  shortcut=QKeySequence.Save,
                                  tip="Enregistre une copie : le fichier d'origine n'est jamais modifié")
        self.act_undo = self._act("Annuler", self.undo, "undo", shortcut=QKeySequence.Undo,
                                  tip="Annuler la dernière action (Ctrl+Z)")
        self.act_redo = self._act("Rétablir", self.redo, "redo",
                                  tip="Rétablir l'action annulée (Ctrl+Y)")
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.act_close_tab = self._act("Fermer l'onglet",
                                       lambda: self.close_tab(self.tabs.currentIndex()),
                                       shortcut=QKeySequence.Close)

        # tools (exclusive)
        group = QActionGroup(self)
        group.setExclusive(True)
        self._tool_actions: dict[Tool, QAction] = {}
        for tool, (label, icon, accent, tip) in self.TOOL_DEFS.items():
            a = self._act(label, None, icon, accent, checkable=True, tip=tip)
            a.triggered.connect(lambda checked, t=tool: self._select_tool(t))
            group.addAction(a)
            self._tool_actions[tool] = a
        self._tool_actions[Tool.SELECT].setChecked(True)

        self.act_color = self._act("Couleur", self.pick_color, "color", accent=True)
        self.act_new_signature = self._act("Nouvelle signature", self.new_signature, "signature")
        self.act_form_mode = self._act("Formulaire", self.toggle_form_mode, "form", checkable=True)

        # measures / plans
        self.act_scale = self._act("Échelle", self.choose_scale, "scale",
                                   tip="Régler l'échelle du plan dans la barre « Mesure »")
        self.act_export_measures = self._act("Exporter mesures", self.export_measures, "export",
                                             tip="Toutes les mesures du document vers Excel (CSV)")
        self.act_compare = self._act("Comparer", self.compare_plans, "compare",
                                     tip="Comparer ce plan avec une autre version (ajouts / suppressions)")
        self.act_grid = self._act("Grille", self.toggle_grid, "grid", checkable=True,
                                  tip="Afficher une grille (pas en mètres si l'échelle est connue)")
        self.act_snap = self._act("Aimanter", self.toggle_snap, "snap", checkable=True,
                                  tip="Accrocher au dessin : extrémités et coins (carré vert), "
                                      "milieux (triangle), et à la grille si elle est affichée. "
                                      "Maj = désactive l'aimant le temps du tracé.")
        self.act_snap.setChecked(bool(self.settings.value("snap", True, type=bool)))

        # pages
        self.act_insert_blank = self._act("Page vierge", self.insert_blank_page, "insertblank")
        self.act_delete_pages = self._act("Supprimer", self.delete_selected_pages, "deletepages")
        self.act_rotate_left = self._act("Rotation -90°", lambda: self.rotate_selected(-90), "rotateleft")
        self.act_rotate_right = self._act("Rotation +90°", lambda: self.rotate_selected(90), "rotateright")
        self.act_insert_pdf = self._act("Insérer un PDF", self.insert_pdf, "insertpdf")
        self.act_extract = self._act("Extraire", self.extract_pages, "extract")
        self.act_split = self._act("Diviser", self.split_document, "split")

        # protect
        self.act_set_password = self._act("Mot de passe", self.set_password, "password")

        # view
        self.act_zoom_in = self._act("Zoom +", lambda: self.zoom_by(1.25), "zoomin",
                                     shortcut=QKeySequence.ZoomIn)
        self.act_zoom_out = self._act("Zoom -", lambda: self.zoom_by(1 / 1.25), "zoomout",
                                      shortcut=QKeySequence.ZoomOut)
        self.act_zoom_100 = self._act("Taille réelle", lambda: self.zoom_to(1.33),
                                      shortcut="Ctrl+0")
        self.act_fit_width = self._act("Pleine largeur", self.fit_width, shortcut="Ctrl+2")
        self.act_fit_page = self._act("Page entière", self.fit_page, shortcut="Ctrl+1")
        self.act_rulers = self._act("Règles", self.toggle_rulers, checkable=True,
                                    tip="Règles graduées (unités réelles si l'échelle est connue)")
        self.act_rulers.setChecked(bool(self.settings.value("rulers", True, type=bool)))
        self.act_gpu = self._act("Accélération matérielle", self.toggle_gpu, checkable=True,
                                 needs_doc=False,
                                 tip="Affichage par la carte graphique (plus fluide). "
                                     "À décocher en cas de souci d'affichage.")
        self.act_gpu.setChecked(bool(self.settings.value("gpu", True, type=bool)))
        self.act_loupe = self._act("Loupe", self.toggle_loupe, "loupe", checkable=True,
                                   tip="Loupe qui suit la souris")
        self.act_invert = self._act("Inverser couleurs", self.toggle_invert, "invert",
                                    checkable=True, tip="Page sombre, traits clairs")
        self.act_split_view = self._act("Vue fractionnée", self.toggle_split_view, "splitview",
                                        checkable=True, tip="Deux vues côte à côte du même document")
        self.act_toggle_theme = self._act("Thème sombre", self.toggle_theme, needs_doc=False)

    def _build_menu(self):
        m = self.menuBar()
        file_menu = m.addMenu("&Fichier")
        for a in (self.act_open, self.act_save, self.act_close_tab):
            file_menu.addAction(a)
        file_menu.addSeparator()
        file_menu.addAction(QAction("Quitter", self, triggered=self.close))

    def _build_ribbon(self):
        self.ribbon = Ribbon()
        holder = QToolBar("Ruban")
        holder.setMovable(False)
        holder.setFloatable(False)
        holder.addWidget(self.ribbon)
        self.addToolBar(holder)
        t = self._tool_actions

        home = self.ribbon.add_page("Accueil")
        for a in (self.act_open, self.act_save):
            home.addAction(a)
        home.addSeparator()
        home.addAction(self.act_undo)
        home.addAction(self.act_redo)
        home.addSeparator()
        home.addAction(t[Tool.SELECT])
        home.addAction(t[Tool.PAN])
        home.addSeparator()
        home.addAction(self.act_zoom_out)
        home.addAction(self.act_zoom_in)
        home.addSeparator()
        home.addAction(t[Tool.TEXTEDIT])
        home.addAction(self.act_form_mode)
        home.addAction(t[Tool.SIGNATURE])
        home.addAction(self.act_new_signature)
        home.addSeparator()
        home.addAction(t[Tool.DIMENSION])
        home.addAction(t[Tool.CAPTURE])
        home.addSeparator()
        home.addAction(self.act_toggle_theme)

        comments = self.ribbon.add_page("Commentaires")
        comments.addAction(t[Tool.SELECT])
        comments.addSeparator()
        for tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT, Tool.FREETEXT, Tool.NOTE):
            comments.addAction(t[tool])
        comments.addSeparator()
        for tool in (Tool.INK, Tool.RECT, Tool.ELLIPSE, Tool.LINE, Tool.ARROW, Tool.CLOUD,
                     Tool.CALLOUT):
            comments.addAction(t[tool])
        comments.addSeparator()
        comments.addAction(t[Tool.STAMP])
        self.stamp_combo = QComboBox()
        self.stamp_combo.addItems(list(STAMP_COLORS.keys()) + [CUSTOM_STAMP])
        self.stamp_combo.setToolTip("Texte du tampon (la date et votre nom sont ajoutés)")
        self.stamp_combo.activated.connect(self._on_stamp_chosen)
        comments.addWidget(self.stamp_combo)
        comments.addSeparator()
        comments.addAction(self.act_color)
        comments.addAction(t[Tool.ERASER])

        measures = self.ribbon.add_page("Mesures")
        measures.addAction(t[Tool.SELECT])
        measures.addSeparator()
        for tool in (Tool.ROOM, Tool.DIMENSION, Tool.MEASURE_PERIMETER, Tool.MEASURE_AREA):
            measures.addAction(t[tool])
        measures.addAction(self.act_scale)
        measures.addSeparator()
        measures.addAction(self.act_grid)
        measures.addAction(self.act_snap)
        measures.addSeparator()
        measures.addAction(self.act_export_measures)
        measures.addAction(self.act_compare)
        measures.addAction(t[Tool.CAPTURE])

        pages = self.ribbon.add_page("Pages")
        for a in (self.act_insert_blank, self.act_delete_pages, self.act_rotate_left,
                  self.act_rotate_right):
            pages.addAction(a)
        pages.addSeparator()
        for a in (self.act_insert_pdf, self.act_extract, self.act_split):
            pages.addAction(a)

        protect = self.ribbon.add_page("Protéger")
        protect.addAction(self.act_set_password)

        view = self.ribbon.add_page("Affichage")
        for a in (self.act_zoom_out, self.act_zoom_in, self.act_zoom_100, self.act_fit_width,
                  self.act_fit_page):
            view.addAction(a)
        view.addSeparator()
        for a in (self.act_rulers, self.act_loupe, self.act_invert, self.act_split_view,
                  self.act_grid, self.act_gpu):
            view.addAction(a)
        view.addSeparator()
        view.addAction(self.act_toggle_theme)

        # properties bar for measurements, right under the ribbon
        self.addToolBarBreak()
        self.measure_bar = MeasureBar()
        self.measure_holder = QToolBar("Propriétés")
        self.measure_holder.setMovable(False)
        self.measure_holder.setFloatable(False)
        self.measure_holder.addWidget(self.measure_bar)
        self.addToolBar(self.measure_holder)
        self.measure_bar.applied.connect(self._on_measure_settings)
        self.measure_bar.colorChanged.connect(self._on_measure_color)
        self.measure_bar.auto_cotes.toggled.connect(self._on_auto_cotes)
        self.measure_bar.text_px.valueChanged.connect(self._on_text_px)
        from . import annotation_items as _ai
        _ai.set_measure_text_px(self.measure_bar.text_px.value())
        self.measure_bar.calibrateRequested.connect(self.start_calibration)

        self.ribbon.set_current(int(self.settings.value("ribbon_tab", 0, type=int)))
        self.ribbon.currentChanged.connect(self._on_ribbon_tab)
        self._update_measure_bar_visibility()
        self._update_theme_action()

    ZOOM_PRESETS = [10, 25, 50, 75, 100, 125, 150, 200, 300, 400, 600, 800, 1200]

    def _build_statusbar(self):
        sb = self.statusBar()
        self.size_label = QLabel("")
        self.cursor_label = QLabel("")
        self.cursor_label.setMinimumWidth(190)
        self.scale_label = QLabel("")
        for w in (self.size_label, self.cursor_label, self.scale_label):
            sb.addPermanentWidget(w)

        # page navigation
        self.btn_prev = QToolButton(text="◀", autoRaise=True)
        self.page_spin = QSpinBox()
        self.page_spin.setMinimum(1)
        self.page_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.page_spin.setAlignment(Qt.AlignCenter)
        self.page_spin.setFixedWidth(46)
        self.page_label = QLabel("/ —")
        self.btn_next = QToolButton(text="▶", autoRaise=True)
        self.btn_prev.clicked.connect(lambda: self._goto_relative(-1))
        self.btn_next.clicked.connect(lambda: self._goto_relative(1))
        self.page_spin.editingFinished.connect(
            lambda: self.current_tab() and self.current_tab().view.goto_page(self.page_spin.value() - 1))
        for w in (self.btn_prev, self.page_spin, self.page_label, self.btn_next):
            sb.addPermanentWidget(w)

        # zoom: - [slider] + [combo %]
        self.btn_zoom_out = QToolButton(text="−", autoRaise=True)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(0, 1000)
        self.zoom_slider.setFixedWidth(130)
        self.btn_zoom_in = QToolButton(text="+", autoRaise=True)
        self.zoom_combo = QComboBox()
        self.zoom_combo.setEditable(True)
        self.zoom_combo.addItems([f"{z} %" for z in self.ZOOM_PRESETS] + ["Pleine largeur", "Page entière"])
        self.zoom_combo.setFixedWidth(118)
        self.zoom_label = self.zoom_combo      # kept for older code paths
        self.btn_zoom_out.clicked.connect(lambda: self.zoom_by(1 / 1.25))
        self.btn_zoom_in.clicked.connect(lambda: self.zoom_by(1.25))
        self.zoom_slider.valueChanged.connect(self._on_zoom_slider)
        self.zoom_combo.activated.connect(self._on_zoom_combo)
        self.zoom_combo.lineEdit().returnPressed.connect(self._on_zoom_combo)
        for w in (self.btn_zoom_out, self.zoom_slider, self.btn_zoom_in, self.zoom_combo):
            sb.addPermanentWidget(w)

    def _update_actions_enabled(self):
        has_doc = self.current_tab() is not None
        for a in self._doc_actions:
            a.setEnabled(has_doc)
        self.stamp_combo.setEnabled(has_doc)
        self._update_undo_actions()
        for w in (self.btn_prev, self.btn_next, self.page_spin, self.btn_zoom_in,
                  self.btn_zoom_out, self.zoom_slider, self.zoom_combo):
            w.setEnabled(has_doc)

    # -- theme ----------------------------------------------------------
    def _update_theme_action(self):
        kind = "theme_light" if self._dark else "theme_dark"
        self.act_toggle_theme.setIcon(self._icon(kind))
        self.act_toggle_theme.setText("Thème clair" if self._dark else "Thème sombre")

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
            for v in self.tabs.widget(i).views():
                v.apply_theme(surround)
        self._apply_icons()

    # -- tab helpers ------------------------------------------------------
    def current_tab(self) -> DocumentTab | None:
        return self.tabs.currentWidget()

    def _on_tab_changed(self, _index):
        tab = self.current_tab()
        self.measure_bar.set_document(tab.pdf_document if tab else None)
        if tab is not None:
            for v in tab.views():
                v.set_tool(self._current_tool)
                v.set_color(self._current_color)
            self._update_page_label(tab.view.current_page())
            self._show_zoom(tab.view.zoom)
            self.act_grid.setChecked(tab.view.show_grid)
            self.act_snap.setChecked(tab.view.snap_to_grid)
            self.act_invert.setChecked(tab.view.invert_colors)
            self.act_split_view.setChecked(tab.view2 is not None)
            self.act_form_mode.setChecked(tab.view.form_mode)
            for v in tab.views():
                v._update_rulers()
        self._update_scale_label()
        self._update_actions_enabled()

    def _update_page_label(self, page_no: int):
        tab = self.current_tab()
        if tab is None:
            return
        n = tab.pdf_document.page_count
        self.page_spin.blockSignals(True)
        self.page_spin.setMaximum(max(1, n))
        self.page_spin.setValue(page_no + 1)
        self.page_spin.blockSignals(False)
        self.page_label.setText(f"/ {n}")
        self.size_label.setText(tab.view.page_size_text())

    def _update_scale_label(self):
        tab = self.current_tab()
        if tab is None:
            self.scale_label.setText("")
            return
        text = tab.pdf_document.scale_description()
        if tab.view.show_grid:
            text += " · " + tab.view.grid_description()
        self.scale_label.setText(text)

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
        self._add_document_tab(doc, os.path.basename(path))

    def _add_document_tab(self, doc: PdfDocument, title: str) -> DocumentTab:
        self.measure_bar.apply_defaults(doc)     # unit / precision before first display
        tab = DocumentTab(doc)
        self._wire_view(tab, tab.view)
        tab.thumbnails.deletePagesRequested.connect(
            lambda pages: self._delete_pages(tab, pages)
        )
        tab.thumbnails.pagesReordered.connect(
            lambda order: self._reorder_pages(tab, order)
        )
        index = self.tabs.addTab(tab, title + (" *" if doc.dirty else ""))
        self.tabs.setCurrentIndex(index)
        return tab

    def _wire_view(self, tab: DocumentTab, view: PdfGraphicsView):
        view.apply_theme(theme_mod.surround_color(self._dark))
        view.set_color(self._current_color)
        view.set_tool(self._current_tool)
        view.stamp_label = self._stamp_label()
        view.documentModified.connect(lambda v=view: self._on_doc_modified(tab, v))
        view.requestTextEdit.connect(
            lambda pno, bbox, text, size, v=view: self._on_text_edit_requested(tab, v, pno, bbox, text, size)
        )
        view.requestSignaturePlacement.connect(
            lambda pno, pt, v=view: self._on_signature_requested(tab, v, pno, pt)
        )
        view.zoomChanged.connect(lambda z, t=tab: self._on_zoom_changed(t, z))
        view.pageChanged.connect(lambda n, t=tab: self.current_tab() is t and self._update_page_label(n))
        view.statusMessage.connect(lambda msg: self.statusBar().showMessage(msg, 5000))
        view.cursorInfo.connect(self.cursor_label.setText)
        view.requestSelectTool.connect(lambda: self._activate_tool(Tool.SELECT))
        view.set_measure_color(self.measure_bar.color)
        view.set_rulers(self.act_rulers.isChecked())
        view.set_gpu(self.act_gpu.isChecked())
        view.snap_to_grid = self.act_snap.isChecked()
        view.auto_cotes = self.measure_bar.auto_cotes.isChecked()
        view.filesDropped.connect(self.open_files)
        view.scaleRequired.connect(self._on_scale_required)
        view.scaleCalibrated.connect(lambda t=tab: self._on_measure_settings())

    def _on_zoom_changed(self, tab: DocumentTab, zoom: float):
        if self.current_tab() is tab:
            self._show_zoom(zoom)
            self._update_scale_label()

    # zoom slider: logarithmic 5 % .. 1600 %
    _ZMIN, _ZMAX = math.log(0.05), math.log(16.0)

    def _show_zoom(self, zoom: float):
        pct = zoom / 1.33 * 100
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setEditText(f"{pct:.0f} %")
        self.zoom_combo.blockSignals(False)
        self.zoom_slider.blockSignals(True)
        v = (math.log(max(zoom, 0.05)) - self._ZMIN) / (self._ZMAX - self._ZMIN) * 1000
        self.zoom_slider.setValue(int(v))
        self.zoom_slider.blockSignals(False)

    def _on_zoom_slider(self, value: int):
        zoom = math.exp(self._ZMIN + value / 1000 * (self._ZMAX - self._ZMIN))
        self.zoom_to(zoom)

    def _on_zoom_combo(self, *_):
        text = self.zoom_combo.currentText().strip()
        if text == "Pleine largeur":
            self.fit_width()
            return
        if text == "Page entière":
            self.fit_page()
            return
        try:
            pct = float(text.replace("%", "").replace(",", ".").strip())
        except ValueError:
            return
        self.zoom_to(pct / 100 * 1.33)

    def _goto_relative(self, delta: int):
        tab = self.current_tab()
        if tab is not None:
            tab.view.goto_page(tab.view.current_page() + delta)

    def fit_width(self):
        tab = self.current_tab()
        if tab is not None:
            tab.view.fit_width()

    def fit_page(self):
        tab = self.current_tab()
        if tab is not None:
            tab.view.fit_page()

    def toggle_gpu(self, checked: bool):
        self.settings.setValue("gpu", checked)
        for i in range(self.tabs.count()):
            for v in self.tabs.widget(i).views():
                v.set_gpu(checked)

    # -- drag & drop of PDF files anywhere on the window ---------------
    def open_files(self, paths):
        for path in paths:
            self.open_file(path)

    def dragEnterEvent(self, event):
        if PdfGraphicsView._pdf_paths(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if PdfGraphicsView._pdf_paths(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = PdfGraphicsView._pdf_paths(event.mimeData())
        if paths:
            event.acceptProposedAction()
            self.open_files(paths)

    def toggle_rulers(self, checked: bool):
        self.settings.setValue("rulers", checked)
        for i in range(self.tabs.count()):
            for v in self.tabs.widget(i).views():
                v.set_rulers(checked)

    # -- measurement properties bar -----------------------------------
    def _on_ribbon_tab(self, index: int):
        self.settings.setValue("ribbon_tab", index)
        self._update_measure_bar_visibility()

    def _update_measure_bar_visibility(self):
        on_tab = self.ribbon.page_titles()[self.ribbon.tab_bar.currentIndex()] == "Mesures" \
            if self.ribbon.tab_bar.count() else False
        visible = on_tab or self._current_tool in MEASURE_TOOLS
        self.measure_holder.setVisible(visible)

    def _on_measure_settings(self):
        tab = self.current_tab()
        if tab is None:
            return
        self.measure_bar.refresh()
        for v in tab.views():
            v.rebuild_annotations()
            v.viewport().update()
            v._update_rulers()
        self._on_doc_modified(tab)
        self.size_label.setText(tab.view.page_size_text())

    def _on_measure_color(self, rgb):
        for i in range(self.tabs.count()):
            for v in self.tabs.widget(i).views():
                v.set_measure_color(rgb)

    def _on_text_px(self, px: int):
        from . import annotation_items as _ai
        self.settings.setValue("cote_text_px", px)
        _ai.set_measure_text_px(px)
        for i in range(self.tabs.count()):
            for v in self.tabs.widget(i).views():
                v._refresh_labels()
                v.rebuild_annotations()

    def _on_auto_cotes(self, checked: bool):
        self.settings.setValue("auto_cotes", checked)
        for i in range(self.tabs.count()):
            for v in self.tabs.widget(i).views():
                v.auto_cotes = checked

    def _on_scale_required(self):
        self.measure_holder.setVisible(True)
        self.measure_bar.flash_warning()

    def start_calibration(self):
        tab = self.current_tab()
        if tab is None:
            return
        self._activate_tool(Tool.DIMENSION)
        for v in tab.views():
            v.start_calibration()

    # -- Annuler / Rétablir ---------------------------------------------
    def _update_undo_actions(self):
        tab = self.current_tab()
        doc = tab.pdf_document if tab else None
        can_u = bool(doc and doc.can_undo())
        can_r = bool(doc and doc.can_redo())
        self.act_undo.setEnabled(can_u)
        self.act_redo.setEnabled(can_r)
        self.act_undo.setToolTip(f"Annuler : {doc.undo_name()} (Ctrl+Z)" if can_u else "Rien à annuler")
        self.act_redo.setToolTip(f"Rétablir : {doc.redo_name()} (Ctrl+Y)" if can_r else "Rien à rétablir")

    def undo(self):
        self._history_step(undo=True)

    def redo(self):
        self._history_step(undo=False)

    def _history_step(self, undo: bool):
        tab = self.current_tab()
        if tab is None:
            return
        doc = tab.pdf_document
        name = doc.undo_name() if undo else doc.redo_name()
        for v in tab.views():
            v._cancel_polygon()
            v._cancel_dimension()
        kind = doc.undo() if undo else doc.redo()
        if kind is None:
            return
        if kind == "annot":
            for v in tab.views():
                v.rebuild_annotations()
        else:
            doc.invalidate_render()
            for v in tab.views():
                v.refresh_all()
            if kind == "pages":
                tab.thumbnails.rebuild(doc)
        self.measure_bar.apply_defaults(doc)      # back to 1:50 if the scale was undone
        self.measure_bar.refresh()
        self._on_doc_modified(tab)
        self._update_page_label(tab.view.current_page())
        self.statusBar().showMessage(("Annulé : " if undo else "Rétabli : ") + name, 4000)

    def _on_doc_modified(self, tab: DocumentTab, source_view: PdfGraphicsView | None = None):
        idx = self.tabs.indexOf(tab)
        title = self.tabs.tabText(idx)
        if not title.endswith("*"):
            self.tabs.setTabText(idx, title + " *")
        # keep the other half of a split view in sync
        for v in tab.views():
            if v is not source_view and source_view is not None:
                v.refresh_all()
        self._update_scale_label()
        self._update_undo_actions()

    def _suggest_save_path(self, tab: DocumentTab) -> str:
        doc = tab.pdf_document
        if doc.path and not doc.is_original(doc.path):
            return doc.path
        src = doc.original_path or os.path.join(os.path.expanduser("~"), "Documents",
                                                (doc.title or "document") + ".pdf")
        base, _ext = os.path.splitext(src)
        return base + "_modifié.pdf"

    def save_current(self, *_args):
        """Always "Enregistrer sous": the opened file is never overwritten."""
        tab = self.current_tab()
        if tab is None:
            return False
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer sous (le fichier d'origine reste intact)",
            self._suggest_save_path(tab), "PDF (*.pdf)"
        )
        if not path:
            return False
        if tab.pdf_document.is_original(path):
            QMessageBox.warning(
                self, "Fichier d'origine",
                "C'est le fichier d'origine : il n'est jamais écrasé.\n"
                "Choisissez un autre nom."
            )
            return self.save_current()
        try:
            if getattr(tab.pdf_document, "_pending_encrypt", None):
                tab.pdf_document.save_with_pending_encryption(path)
            else:
                tab.pdf_document.save(path)
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Échec de l'enregistrement :\n{exc}")
            return False
        idx = self.tabs.indexOf(tab)
        self.tabs.setTabText(idx, os.path.basename(path))
        self.statusBar().showMessage(f"Enregistré : {path}", 6000)
        return True

    def close_tab(self, index: int):
        tab = self.tabs.widget(index)
        if tab is None:
            return
        if tab.dirty:
            box = QMessageBox(QMessageBox.Question, "Modifications non enregistrées",
                              f"« {self.tabs.tabText(index).rstrip(' *')} » a été modifié.\n"
                              "Enregistrer les modifications avant de fermer ?", parent=self)
            btn_save = box.addButton("Enregistrer…", QMessageBox.AcceptRole)
            btn_discard = box.addButton("Ne pas enregistrer", QMessageBox.DestructiveRole)
            btn_cancel = box.addButton("Annuler", QMessageBox.RejectRole)
            box.setDefaultButton(btn_save)
            box.setEscapeButton(btn_cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is btn_cancel or clicked is None:
                return
            if clicked is btn_save:
                self.tabs.setCurrentIndex(index)
                if not self.save_current():
                    return
        for v in tab.views():
            v.shutdown()
        tab.pdf_document.close()
        self.tabs.removeTab(index)

    # -- tools ------------------------------------------------------------
    def _select_tool(self, tool: Tool):
        self._current_tool = tool
        tab = self.current_tab()
        if tab is not None:
            for v in tab.views():
                v.set_tool(tool)
        if hasattr(self, "measure_holder"):
            self._update_measure_bar_visibility()

    def _activate_tool(self, tool: Tool):
        self._tool_actions[tool].setChecked(True)
        self._select_tool(tool)

    def pick_color(self):
        """Colour window that stays open: every colour clicked is applied
        at once, so you can pick a colour and keep highlighting / drawing
        without validating anything."""
        dlg = getattr(self, "_color_dlg", None)
        if dlg is None:
            dlg = QColorDialog(QColor.fromRgbF(*self._current_color), self)
            dlg.setWindowTitle("Couleur — reste ouverte, cliquez une couleur puis continuez")
            dlg.setOption(QColorDialog.DontUseNativeDialog, True)
            dlg.setOption(QColorDialog.NoButtons, True)
            dlg.setWindowFlag(Qt.Tool, True)
            dlg.setModal(False)
            dlg.currentColorChanged.connect(self._set_current_color)
            self._color_dlg = dlg
        dlg.setCurrentColor(QColor.fromRgbF(*self._current_color))
        dlg.show()
        dlg.raise_()

    def _set_current_color(self, c: QColor):
        if not c.isValid():
            return
        self._current_color = (c.redF(), c.greenF(), c.blueF())
        for i in range(self.tabs.count()):
            for v in self.tabs.widget(i).views():
                v.set_color(self._current_color)
        self._apply_icons()

    def _stamp_label(self) -> str:
        if not hasattr(self, "_custom_stamp"):
            self._custom_stamp = ""
        text = self.stamp_combo.currentText() if hasattr(self, "stamp_combo") else "APPROUVÉ"
        if text == CUSTOM_STAMP:
            return self._custom_stamp or "VU"
        return text

    def _on_stamp_chosen(self, _index):
        if self.stamp_combo.currentText() == CUSTOM_STAMP:
            text, ok = QInputDialog.getText(self, "Tampon personnalisé",
                                            "Texte du tampon :", text=getattr(self, "_custom_stamp", ""))
            if ok and text.strip():
                self._custom_stamp = text.strip().upper()
        label = self._stamp_label()
        for i in range(self.tabs.count()):
            for v in self.tabs.widget(i).views():
                v.stamp_label = label
        self._activate_tool(Tool.STAMP)

    def new_signature(self):
        dlg = SignatureDialog(self)
        if dlg.exec() == QDialog.Accepted and not dlg.canvas.is_empty():
            self._signature_png = dlg.png_bytes()
            self._activate_tool(Tool.SIGNATURE)

    def toggle_form_mode(self, checked: bool):
        tab = self.current_tab()
        if tab is not None:
            tab.view.set_form_mode(checked)

    # -- plans / measures ----------------------------------------------
    def choose_scale(self):
        self.measure_holder.setVisible(True)
        self.measure_bar.flash_warning()

    def reset_scale(self):
        tab = self.current_tab()
        if tab is not None:
            tab.pdf_document.scale_points_per_meter = None
            self._update_scale_label()

    def export_measures(self):
        tab = self.current_tab()
        if tab is None:
            return
        doc = tab.pdf_document
        if not doc.measurements():
            QMessageBox.information(self, "Exporter les mesures",
                                    "Ce document ne contient encore aucune mesure.")
            return
        base = os.path.splitext(doc.original_path or doc.path or "mesures")[0]
        path, _ = QFileDialog.getSaveFileName(self, "Exporter les mesures (Excel)",
                                              base + "_mesures.csv", "CSV pour Excel (*.csv)")
        if not path:
            return
        try:
            n = doc.export_measurements_csv(path)
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Export impossible :\n{exc}")
            return
        if QMessageBox.question(self, "Mesures exportées",
                                f"{n} mesure(s) exportée(s).\nOuvrir le fichier dans Excel ?"
                                ) == QMessageBox.Yes:
            os.startfile(path)

    def compare_plans(self):
        tab = self.current_tab()
        if tab is None:
            return
        import pymupdf
        from .compare import build_comparison_pdf
        path, _ = QFileDialog.getOpenFileName(
            self, "Nouvelle version du plan à comparer", "", "PDF (*.pdf)")
        if not path:
            return
        try:
            other = pymupdf.open(path)
            if other.needs_pass:
                pw = ask_password(self, os.path.basename(path))
                if not pw or not other.authenticate(pw):
                    return
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Impossible d'ouvrir :\n{exc}")
            return
        old_name = os.path.basename(tab.pdf_document.original_path or "ce document")
        new_name = os.path.basename(path)
        counts_differ = tab.pdf_document.page_count != other.page_count
        n_total = min(tab.pdf_document.page_count, other.page_count)
        progress = QProgressDialog("Comparaison en cours…", "Annuler", 0, n_total, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(300)

        def step(i, n):
            progress.setValue(i)
            QApplication.processEvents()
            return not progress.wasCanceled()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data, n = build_comparison_pdf(tab.pdf_document, other, old_name, new_name,
                                           progress=step)
        except Exception as exc:
            QMessageBox.critical(self, "Erreur", f"Comparaison impossible :\n{exc}")
            return
        finally:
            QApplication.restoreOverrideCursor()
            progress.close()
            other.close()
        if n == 0:
            return
        title = f"Comparaison {os.path.splitext(old_name)[0]}"
        doc = PdfDocument(data=data, title=title)
        self._add_document_tab(doc, title)
        extra = " (nombre de pages différent : seules les premières sont comparées)" \
            if counts_differ else ""
        self.statusBar().showMessage(
            f"{n} page(s) comparée(s) — rouge = supprimé, vert = ajouté.{extra}", 10000)

    def toggle_grid(self, checked: bool):
        tab = self.current_tab()
        if tab is not None:
            for v in tab.views():
                v.set_grid(checked)
        self._update_scale_label()

    def toggle_snap(self, checked: bool):
        self.settings.setValue("snap", checked)
        for i in range(self.tabs.count()):
            for v in self.tabs.widget(i).views():
                v.snap_to_grid = checked
                if checked:
                    v._prepare_snap()

    def toggle_loupe(self, checked: bool):
        for i in range(self.tabs.count()):
            for v in self.tabs.widget(i).views():
                v.set_loupe(checked)

    def toggle_invert(self, checked: bool):
        tab = self.current_tab()
        if tab is not None:
            for v in tab.views():
                v.set_invert(checked)

    def toggle_split_view(self, checked: bool):
        tab = self.current_tab()
        if tab is None:
            return
        if checked and tab.view2 is None:
            v2 = PdfGraphicsView(tab.pdf_document)
            v2.set_zoom(tab.view.zoom)
            v2.set_grid(tab.view.show_grid)
            v2.snap_to_grid = tab.view.snap_to_grid
            if tab.view.invert_colors:
                v2.set_invert(True)
            v2.set_loupe(self.act_loupe.isChecked())
            tab.view2 = v2
            tab.view_splitter.addWidget(v2)
            self._wire_view(tab, v2)
            v2.refresh_all()
            v2.goto_page(tab.view.current_page())
        elif not checked and tab.view2 is not None:
            v2 = tab.view2
            tab.view2 = None
            v2.shutdown()
            v2.setParent(None)
            v2.deleteLater()

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

    # -- page operations ----------------------------------------------
    def _refresh_thumbs(self, tab: DocumentTab):
        tab.thumbnails.rebuild(tab.pdf_document)
        for v in tab.views():
            v.refresh_all()
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
    def _on_text_edit_requested(self, tab: DocumentTab, view, page_no, bbox, text, fontsize):
        dlg = TextEditDialog(self, text, fontsize)
        if dlg.exec() == QDialog.Accepted:
            new_text, size = dlg.values()
            view.apply_text_edit(page_no, bbox, new_text, size)

    def _on_signature_requested(self, tab: DocumentTab, view, page_no, pt):
        if self._signature_png is None:
            dlg = SignatureDialog(self)
            if dlg.exec() != QDialog.Accepted or dlg.canvas.is_empty():
                return
            self._signature_png = dlg.png_bytes()
        view.place_signature_image(page_no, pt, self._signature_png)

    # -- close handling -----------------------------------------------
    def closeEvent(self, event):
        while self.tabs.count():
            before = self.tabs.count()
            self.close_tab(0)
            if self.tabs.count() == before:
                event.ignore()
                return
        event.accept()
