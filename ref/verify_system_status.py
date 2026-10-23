"""Verify a real Windows system-status canvas with synthetic data only, without any socket."""

import argparse
import csv
import json
import math
from pathlib import Path
import sys
import time
from unittest.mock import patch

GS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(GS))
import stereo_runtime
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication
from ui.system_status import SystemStatusWidget


def main():
    """Render half-hour synthetic traces, verify visible CSV/XLSX/PNG and preserve all history."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = QApplication([])
    app.setFont(QFont('Microsoft YaHei', 10))
    page = SystemStatusWidget()
    page.resize(1080, 900)
    page.setWindowTitle('系统状态离线验收 · 演示数据，非实测 · 不连接机器鱼')
    page.condition_input.setText('演示数据：充电宝 / 无风扇；不是散热实验结果')
    page.set_connected(True)
    origin = time.monotonic()-1800.
    try:
        with patch.object(page, '_render'), patch.object(page, '_refresh_status'):
            for index in range(3601):
                second = index/2.
                if 1200. < second < 1220.:
                    continue
                page.add_sample(dict(cpu_percent=25.+7.*math.sin(second/70.),
                    soc_temp_c=42.+24.*(1.-math.exp(-second/500.)),
                    mem_used_mb=1050.+second/20., mem_total_mb=4096., cpu_freq_mhz=1800.),
                    received_at=origin+second, source_timestamp=1700000000.+second)
        page.show()
        page._render()
        page._refresh_status()
        app.processEvents()
        page.grab().save(str(output/'system-status-global.png'))
        page.export_png(output/'canvas-global.png')
        page.sliding_time_cb.setChecked(True)
        page.sliding_window_input.setValue(300)
        assert page.visible_rows()[0]['time_s'] == 1500.
        page.grab().save(str(output/'system-status-sliding.png'))
        page.follow_latest = False
        page.plots[0].setXRange(600., 900., padding=0)
        app.processEvents()
        _, count = page.export_data(output/'visible.csv')
        page.export_data(output/'visible.xlsx')
        page.export_png(output/'canvas-visible.png')
        assert count == 601
        with (output/'visible.csv').open(encoding='utf-8-sig', newline='') as stream:
            saved = list(csv.DictReader(stream))
        assert saved[0]['time_s'] == '600.0' and saved[-1]['time_s'] == '900.0'
        page.reset_view()
        assert len(page.rows) == 3563
        page.set_connected(False)
        page.grab().save(str(output/'system-status-disconnected.png'))
        result = dict(platform=app.platformName(), synthetic_only=True, physical_commands=0,
                      history_rows=len(page.rows), visible_export_rows=count,
                      export_range_s=[600, 900], gap_rows=sum(r['status']=='gap' for r in page.rows),
                      plots=3, no_personal_config_writes=True)
        (output/'summary.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    finally:
        page.status_timer.stop()
        page.close()
        app.processEvents()


if __name__ == '__main__':
    main()
