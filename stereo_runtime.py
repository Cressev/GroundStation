"""Prefer the project's optional contrib runtime without replacing global OpenCV."""

from pathlib import Path
import importlib.util
import sys


def bootstrap():
    """Prefer project-local OpenCV and use isolated PyAV when the environment lacks it."""
    target = str(Path(__file__).resolve().parent / '.runtime' / 'opencv')
    if Path(target, 'cv2').is_dir() and target not in sys.path:
        sys.path.insert(0, target)
    pyav = Path(__file__).resolve().parent / '.runtime' / 'pyav'
    if importlib.util.find_spec('av') is None and (pyav/'av').is_dir():
        if str(pyav) not in sys.path:
            sys.path.insert(0, str(pyav))
    # Reuse GUI-only dependencies when the mandated agentscope interpreter lacks Qt.
    # This changes this process's import path, not either Conda environment on disk.
    qt_packages = Path(sys.prefix).parent/'qt5'/'Lib'/'site-packages'
    if importlib.util.find_spec('PyQt5') is None and (qt_packages/'PyQt5').is_dir():
        if str(qt_packages) not in sys.path:
            sys.path.append(str(qt_packages))


bootstrap()
