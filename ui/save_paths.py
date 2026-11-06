"""Shared safe export names and project-local default directories."""
from datetime import datetime
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1] / 'saved_data'
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$', re.I)


def validate_label(value):
    """Return a portable optional filename label or explain why it is invalid."""
    if not isinstance(value, str):
        raise ValueError('文件名必须为文字')
    if not value:
        return ''
    if len(value) > 100 or value != value.strip() or value.endswith('.'):
        raise ValueError('文件名不能超过100个字符，不能以空格或点结尾，也不能以空格开头')
    if _INVALID.search(value) or value in ('.', '..') or _RESERVED.fullmatch(value):
        raise ValueError('文件名不能包含路径分隔符、特殊字符或 Windows 保留名称')
    return value


def default_export_path(category, label, suffix, now=None):
    """Generate an unused timestamped path beneath the fixed project export directory."""
    if category not in ('videos', 'stereo_videos', 'top_camera_videos', 'time_series', 'system_status', 'images'):
        raise ValueError('未知保存类别')
    label = validate_label(label)
    if not re.fullmatch(r'\.[a-z0-9]+', suffix):
        raise ValueError('非法文件扩展名')
    directory = ROOT / category
    directory.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime('%Y%m%d_%H%M%S')
    stem = stamp + ('_' + label if label else '')
    path = directory / (stem + suffix)
    counter = 2
    while path.exists():
        path = directory / (stem + '_' + str(counter) + suffix)
        counter += 1
    return path
