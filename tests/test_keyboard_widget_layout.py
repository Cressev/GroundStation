# -*- coding: utf-8 -*-
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication

from controllers.base import KeyboardController


def main():
    app = QApplication.instance() or QApplication([])
    controller = KeyboardController()
    widget = controller.get_control_widget()

    assert widget.minimumWidth() >= 0
    for name, spin in controller._param_inputs.items():
        assert spin.minimumWidth() >= 96, f"{name} has no protective minimum width"
        assert spin.maximumWidth() >= spin.minimumWidth(), f"{name} maximum width is too small"

    print("keyboard widget layout test passed")


if __name__ == "__main__":
    main()
