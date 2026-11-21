"""Missing depth values must not crash Qt slots or poison recording/calibration."""
import math
from unittest.mock import Mock

import pytest
from PyQt5.QtWidgets import QApplication

import ui.depth_panel as module

_APP = None


@pytest.fixture
def panel(monkeypatch, tmp_path):
    """Create a disconnected widget using only a disposable zero file."""
    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(module, 'ZERO_PATH', tmp_path/'depth-zero.json')
    widget = module.DepthPanel('unused.invalid')
    yield widget
    widget.recording = False
    widget._calibrating = False
    widget.close()


def test_second_channel_survives_first_channel_null(panel):
    """Keep channel 1 missing rather than zero while showing valid channel 2/fusion."""
    panel.zero_offset = 2.
    panel.recording = True
    panel._on_line(dict(type='depth', raw_1=None, filtered_1=None,
                       raw_2=16., filtered_2=15.5, fused=15.5))
    assert '1路' in panel.raw_label.text() and '无数据' in panel.raw_label.text()
    assert '2路' in panel.raw_label.text() and '16.0' in panel.raw_label.text()
    assert '\n' in panel.raw_label.text()
    assert panel.raw_label.minimumHeight() >= 2*panel.raw_label.fontMetrics().lineSpacing()
    assert '15.5' in panel.filtered_label.text()
    assert panel.depth_big_label.text() == '+13.5 cm'
    assert panel.records[-1][1:] == [None, None, 15.5, 13.5]


@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), -float('inf'),
                                 'broken', {}, [], True, 10**400])
def test_invalid_values_clear_previous_display_and_do_not_enter_calibration(panel, bad):
    """A bad sample must not retain stale numbers or enter a calibration mean."""
    panel._on_line(dict(type='depth', raw_1=8., filtered_1=7., fused=7.))
    panel._calibrating = True
    panel.recording = True
    panel._on_line(dict(type='depth', raw_1=bad, filtered_1=bad, fused=bad))
    assert panel.depth_big_label.text() == '--.-- cm'
    assert '无数据' in panel.raw_label.text()
    assert '无数据' in panel.filtered_label.text()
    assert '无数据' in panel.fused_label.text()
    assert not panel._calib_samples
    assert panel.records[-1][1:] == [None, None, None, None]


def test_missing_fields_are_not_synthetic_zero(panel):
    """Omitted fields are unknown values, not real zero-depth measurements."""
    panel.recording = True
    panel._on_line(dict(type='depth'))
    assert '无数据' in panel.raw_label.text()
    assert panel.records[-1][1:] == [None]*4


def test_valid_zero_negative_and_legacy_single_channel_remain_valid(panel):
    """Zero and negative depths are legitimate and legacy text stays compatible."""
    panel._on_line(dict(type='depth', raw_1=0., filtered_1=-1., fused=0.))
    assert panel.raw_label.text() == '原始: 0.0 cm'
    assert panel.filtered_label.text() == '滤波: -1.0 cm'
    assert panel.depth_big_label.text() == '+0.0 cm'


def test_repeated_missing_then_recovery_keeps_recording(panel):
    """Repeated hardware-fault packets and later recovery never break the slot."""
    panel.recording = True
    panel._calibrating = True
    for _ in range(100):
        panel._on_line(dict(type='depth', raw_1=None, filtered_1=None,
                           raw_2=20., filtered_2=19., fused=19.))
    panel._on_line(dict(type='depth', raw_1=18., filtered_1=18.5,
                       raw_2=20., filtered_2=19.5, fused=19.))
    assert len(panel.records) == 101 and len(panel._calib_samples) == 101
    assert '无数据' not in panel.raw_label.text()
    assert all(math.isfinite(v) for v in panel._calib_samples)


def test_csv_preserves_empty_missing_cells_and_valid_fusion(panel, monkeypatch, tmp_path):
    """CSV export preserves the existing columns without writing None/NaN as zero."""
    import csv
    output = tmp_path/'depth.csv'
    monkeypatch.setattr(module.QFileDialog, 'getSaveFileName', lambda *a, **k: (str(output), 'CSV'))
    monkeypatch.setattr(module.QMessageBox, 'information', Mock())
    panel.recording = True
    panel._on_line(dict(type='depth', raw_1=None, filtered_1=None, raw_2=5., filtered_2=4., fused=4.))
    panel._stop_recording()
    with output.open(encoding='utf-8', newline='') as stream:
        rows = list(csv.reader(stream))
    assert rows[1][1:3] == ['', '']
    assert rows[1][3:] == ['4.0', '4.0']
