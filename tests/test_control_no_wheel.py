"""Real Qt wheel, keyboard and scroll-page behavior for every controller number field."""

from unittest.mock import Mock

import pytest
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtTest import QTest, QSignalSpy
from PyQt5.QtWidgets import QApplication, QAbstractSpinBox, QScrollArea, QStyle, QStyleOptionSpinBox

from controllers.base import KeyboardController
from controllers.depth import DepthController
from controllers.xbox import XboxController
from test_ui_state_machine import ensure_app
from ui.numeric_inputs import NoWheelDoubleSpinBox, NoWheelSpinBox


def wheel(target, delta=120, pixels=0):
    """Deliver an actual wheel event to either a spin-box frame or its editor."""
    point = target.rect().center()
    event = QWheelEvent(QPointF(point), QPointF(target.mapToGlobal(point)),
        QPoint(0, pixels), QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
        Qt.NoScrollPhase, False)
    QApplication.sendEvent(target, event)
    return event


@pytest.fixture(params=['keyboard', 'depth', 'xbox'])
def panel(request, tmp_path):
    """Build inactive, offline panels without applying or saving parameter edits."""
    app = ensure_app()
    if request.param == 'keyboard':
        controller = KeyboardController()
    elif request.param == 'depth':
        controller = DepthController(params_path=tmp_path/'depth.json')
    else:
        controller = XboxController(backend=Mock())
        controller._poll_timer.stop()
    widget = controller.get_control_widget()
    if request.param == 'depth':
        controller._parameter_unlock_checkbox.setChecked(True)
    widget.show()
    app.processEvents()
    spins = widget.findChildren(QAbstractSpinBox)
    assert len(spins) == {'keyboard': 9, 'depth': 18, 'xbox': 13}[request.param]
    assert all(isinstance(spin, (NoWheelSpinBox, NoWheelDoubleSpinBox)) for spin in spins)
    yield app, widget, spins
    controller._update_timer.stop() if hasattr(controller, '_update_timer') else None
    widget.close()


def test_every_numeric_parameter_ignores_wheel_with_or_without_focus(panel):
    """All 40 controls ignore wheel/notches/trackpad input, including focused editors."""
    app, widget, spins = panel
    for spin in spins:
        spy = QSignalSpy(spin.valueChanged)
        original = spin.value()
        for focused in (False, True):
            spin.setFocus() if focused else spin.clearFocus()
            app.processEvents()
            for target in (spin, spin.lineEdit()):
                for delta, pixels in ((120, 0), (-120, 0), (0, 15), (0, -15)):
                    wheel(target, delta, pixels)
                    assert spin.value() == original
        assert len(spy) == 0


def test_keyboard_arrows_typing_and_step_buttons_still_work(panel):
    """Every parameter retains keyboard arrows, direct text editing and mouse step buttons."""
    app, widget, spins = panel
    for spin in spins:
        midpoint = (spin.minimum()+spin.maximum())/2
        spin.setValue(int(midpoint) if isinstance(spin, NoWheelSpinBox) else midpoint)
        original = spin.value()
        spin.setFocus()
        QTest.keyClick(spin, Qt.Key_Up)
        assert spin.value() == pytest.approx(original+spin.singleStep())
        QTest.keyClick(spin.lineEdit(), Qt.Key_Down)
        assert spin.value() == pytest.approx(original)
        spin.lineEdit().selectAll()
        QTest.keyClicks(spin.lineEdit(), str(spin.minimum()))
        QTest.keyClick(spin.lineEdit(), Qt.Key_Return)
        assert spin.value() == spin.minimum()
        option = QStyleOptionSpinBox()
        spin.initStyleOption(option)
        button = spin.style().subControlRect(QStyle.CC_SpinBox, option,
                                             QStyle.SC_SpinBoxUp, spin)
        QTest.mouseClick(spin, Qt.LeftButton, pos=button.center())
        assert spin.value() == pytest.approx(spin.minimum()+spin.singleStep())


@pytest.mark.parametrize('focused', [False, True])
def test_wheel_over_editor_scrolls_parent_instead_of_changing_value(focused):
    """Ignoring the event must preserve scrolling, not swallow it inside the editor."""
    app = ensure_app()
    from PyQt5.QtWidgets import QWidget, QVBoxLayout
    content = QWidget()
    layout = QVBoxLayout(content)
    spin = NoWheelDoubleSpinBox()
    spin.setValue(25)
    layout.addWidget(spin)
    layout.addStretch()
    content.setMinimumHeight(1500)
    area = QScrollArea()
    area.setWidget(content)
    area.setWidgetResizable(True)
    area.resize(400, 300)
    area.show()
    app.processEvents()
    spin.setFocus() if focused else spin.clearFocus()
    try:
        before = area.verticalScrollBar().value()
        wheel(spin.lineEdit(), -120)
        app.processEvents()
        assert spin.value() == 25
        assert area.verticalScrollBar().value() > before
    finally:
        area.close()
