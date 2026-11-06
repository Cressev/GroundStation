"""Check suggested paths and rejection before opening a save dialog."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from test_ui_state_machine import ensure_app
from ui import save_paths
from ui.system_status import SystemStatusWidget
from ui.visualization import DataVisualizationWidget


@pytest.mark.parametrize('kind', ['time', 'system'])
def test_export_label_and_default_directory(tmp_path, monkeypatch, kind):
    """CSV and PNG dialogs start in their dedicated directory and use the label."""
    from PyQt5.QtWidgets import QFileDialog, QMessageBox
    ensure_app()
    monkeypatch.setattr(save_paths, 'ROOT', tmp_path/'exports')
    dialog = Mock(return_value=('', ''))
    warning = Mock()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', dialog)
    monkeypatch.setattr(QMessageBox, 'warning', warning)
    widget = DataVisualizationWidget() if kind == 'time' else SystemStatusWidget()
    name = widget.time_export_name if kind == 'time' else widget.export_name
    export_data = widget._save_visible_time_data if kind == 'time' else widget._save_data
    export_image = widget._save_time_series_image if kind == 'time' else widget._save_image
    category = 'time_series' if kind == 'time' else 'system_status'
    name.setText('试验一')
    for action, ext in ((export_data, '.csv'), (export_image, '.png')):
        action()
        suggested = Path(dialog.call_args.args[2])
        assert suggested.parent == tmp_path/'exports'/category
        assert suggested.name.endswith('_试验一'+ext)
    calls = dialog.call_count
    name.setText('../bad')
    export_data()
    assert dialog.call_count == calls and warning.called
    widget.close()
