"""Render an isolated depth panel and replay missing sensor packets without networking."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import stereo_runtime
from PyQt5.QtWidgets import QApplication
from ui import depth_panel as module


def hashes():
    """Track the user's runtime files without reading their contents into the report."""
    return {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
            if (ROOT/name).exists() else None
            for name in ('depth_zero.json', 'keyboard_params.json', 'connections.json')}


def main():
    """Replay queued Qt messages, save native screenshots, and verify no personal writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--replay', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = hashes()
    module.ZERO_PATH = output/'isolated-zero.json'
    errors = []
    sys.excepthook = lambda kind, value, trace: errors.append(str(value))
    app = QApplication([])
    panel = module.DepthPanel('unused.invalid')
    panel.resize(320, 640)
    panel.show()
    records = []
    if args.replay:
        for line in args.replay.read_text(encoding='utf-8').splitlines():
            item = json.loads(line)
            payload = item.get('payload', item)
            if payload.get('type') == 'depth':
                records.append(payload)
    if not records:
        records = [dict(type='depth', raw_1=None, filtered_1=None, raw_2=16., filtered_2=15.5, fused=15.5)]*100
    panel.recording = True
    for value in records:
        panel.client.line_received.emit(value)
    app.processEvents()
    app.processEvents()  # Process layout requests posted by the queued depth slots.
    panel.grab().save(str(output/'first_missing.png'))
    replay_labels = dict(raw=panel.raw_label.text(), filtered=panel.filtered_label.text(),
                         fused=panel.fused_label.text(), big=panel.depth_big_label.text())
    replay_count = len(panel.records)
    panel.client.line_received.emit(dict(type='depth', raw_1=None, filtered_1=None,
                                        raw_2=None, filtered_2=None, fused=None))
    app.processEvents()
    app.processEvents()
    panel.grab().save(str(output/'both_missing.png'))
    assert panel.depth_big_label.text() == '--.-- cm'
    panel.client.line_received.emit(dict(type='depth', raw_1=15., filtered_1=15.,
                                        raw_2=16., filtered_2=16., fused=15.5))
    app.processEvents()
    app.processEvents()
    panel.grab().save(str(output/'recovered.png'))
    assert '无数据' not in panel.raw_label.text()
    panel.recording = False
    panel.close()
    app.processEvents()
    after = hashes()
    assert before == after
    assert replay_count == len(records) and not errors
    result = dict(replayed_depth_packets=len(records), recorded_rows=replay_count,
        labels=replay_labels, qt_slot_errors=errors, personal_files_unchanged=True,
        hardware_connections=0, python=sys.executable)
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
