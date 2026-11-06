"""Portable filenames, project-root defaults and collision handling."""
from datetime import datetime

import pytest

import ui.save_paths as paths


@pytest.mark.parametrize('name', ['../x', 'a/b', 'a\\b', 'x:y', 'a*', 'a?',
                                  'CON', 'com1.txt', 'name.', ' name', 'x\n'])
def test_invalid_labels_are_rejected(name):
    """Windows reserved names and paths are rejected on every platform."""
    with pytest.raises(ValueError):
        paths.validate_label(name)


def test_timestamp_and_collision(tmp_path, monkeypatch):
    """Labels remain readable, empty names work and existing files are not replaced."""
    monkeypatch.setattr(paths, 'ROOT', tmp_path)
    now = datetime(2026, 11, 6, 12, 34, 56)
    p = paths.default_export_path('videos', '水下测试', '.mp4', now)
    assert p == tmp_path / 'videos' / '20261106_123456_水下测试.mp4'
    p.touch()
    assert paths.default_export_path('videos', '水下测试', '.mp4', now).stem.endswith('_2')
    assert paths.default_export_path('images', '', '.png', now).name == '20261106_123456.png'
    stereo = paths.default_export_path('stereo_videos', '试验', '.mp4', now)
    top = paths.default_export_path('top_camera_videos', '试验', '.mp4', now)
    assert stereo.parent != top.parent
