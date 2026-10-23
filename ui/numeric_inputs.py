"""Controller number fields: wheel scrolls the page, never changes a parameter."""

from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import QApplication, QAbstractScrollArea, QDoubleSpinBox, QSpinBox


def forward_wheel_to_page(editor, event):
    """Scroll the nearest enclosing page once, preserving trackpad deltas and phase."""
    parent = editor.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            viewport = parent.viewport()
            forwarded = QWheelEvent(QPointF(viewport.mapFromGlobal(event.globalPos())),
                event.globalPosF(), event.pixelDelta(), event.angleDelta(),
                event.buttons(), event.modifiers(), event.phase(), event.inverted(), event.source())
            QApplication.sendEvent(viewport, forwarded)
            event.setAccepted(forwarded.isAccepted())
            return
        parent = parent.parentWidget()
    event.ignore()


class NoWheelSpinBox(QSpinBox):
    """Integer editor retaining normal typing, arrow keys and step buttons."""

    def __init__(self, parent=None):
        """Allow click/Tab focus, not focus acquired from a passing wheel."""
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.lineEdit().installEventFilter(self)

    def wheelEvent(self, event):
        """Send wheel input to the page instead of stepping the value."""
        forward_wheel_to_page(self, event)

    def eventFilter(self, watched, event):
        """Handle the text child too, without changing its normal keyboard behavior."""
        if event.type() == QEvent.Wheel and watched is self.lineEdit():
            forward_wheel_to_page(self, event)
            return True
        return super().eventFilter(watched, event)


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    """Floating-point editor that cannot change values through wheel input."""

    def __init__(self, parent=None):
        """Preserve keyboard accessibility and the standard spin-box UI."""
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.lineEdit().installEventFilter(self)

    def wheelEvent(self, event):
        """Forward wheel input even while the editor already has focus."""
        forward_wheel_to_page(self, event)

    def eventFilter(self, watched, event):
        """Forward wheel events on the text child and retain Qt's editing filters."""
        if event.type() == QEvent.Wheel and watched is self.lineEdit():
            forward_wheel_to_page(self, event)
            return True
        return super().eventFilter(watched, event)
