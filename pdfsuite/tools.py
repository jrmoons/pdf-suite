from enum import Enum, auto


class Tool(Enum):
    PAN = auto()
    SELECT = auto()
    HIGHLIGHT = auto()
    UNDERLINE = auto()
    STRIKEOUT = auto()
    FREETEXT = auto()
    NOTE = auto()
    INK = auto()
    RECT = auto()
    ELLIPSE = auto()
    LINE = auto()
    ERASER = auto()
    TEXTEDIT = auto()
    SIGNATURE = auto()
    MEASURE_LINE = auto()
    MEASURE_PERIMETER = auto()


DRAG_TOOLS = {Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT, Tool.RECT,
              Tool.ELLIPSE, Tool.LINE, Tool.INK, Tool.MEASURE_LINE}

CLICK_TOOLS = {Tool.FREETEXT, Tool.NOTE, Tool.ERASER, Tool.TEXTEDIT, Tool.SIGNATURE}

# Tools handled with their own multi-click state machine (not a simple drag).
POLY_TOOLS = {Tool.MEASURE_PERIMETER}

DEFAULT_COLOR = {
    Tool.HIGHLIGHT: (1.0, 0.85, 0.2),
    Tool.UNDERLINE: (0.1, 0.4, 1.0),
    Tool.STRIKEOUT: (1.0, 0.1, 0.1),
    Tool.INK: (0.9, 0.1, 0.1),
    Tool.RECT: (0.9, 0.1, 0.1),
    Tool.ELLIPSE: (0.9, 0.1, 0.1),
    Tool.LINE: (0.9, 0.1, 0.1),
    Tool.FREETEXT: (0.0, 0.0, 0.0),
    Tool.MEASURE_LINE: (0.0, 0.55, 0.9),
    Tool.MEASURE_PERIMETER: (0.0, 0.55, 0.9),
}
