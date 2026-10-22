"""Install a private WLS-capable OpenCV; never uninstall the active environment."""

from pathlib import Path
import subprocess
import sys


def main():
    """Install the pinned wheel into a project-local, ignored runtime directory."""
    target = Path(__file__).resolve().parents[1] / '.runtime' / 'opencv'
    if target.exists():
        raise SystemExit('Runtime already exists; inspect it instead of overwriting')
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps',
                    '--only-binary=:all:', '--target', str(target),
                    'opencv-contrib-python==4.11.0.86'], check=True)


if __name__ == '__main__':
    main()
