"""Install a pinned PyAV into the isolated project runtime, not a Conda environment."""
from pathlib import Path
import subprocess
import sys


def main():
    """Refuse to overwrite an existing runtime and install for the active interpreter."""
    target = Path(__file__).resolve().parents[1]/'.runtime'/'pyav'
    if target.exists():
        raise SystemExit(f'目标已存在，未覆盖：{target}；请先检查并备份该目录。')
    if sys.version_info[:2] != (3, 10):
        raise SystemExit('本项目已验证 Python 3.10；请在地面站实际使用的环境运行。')
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--target', str(target),
                    'av==17.0.0'], check=True)
    print(f'PyAV 已安装到 {target}；重启地面站后生效。')


if __name__ == '__main__':
    main()
