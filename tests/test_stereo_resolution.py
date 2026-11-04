"""Resolution controls and uncalibrated preview without real camera access."""

import hashlib
import json

import cv2
import numpy as np
import pytest

from test_npz_selection import npz_bytes
from test_ui_state_machine import ensure_app
from ui.stereo_camera_widget import StereoFishCameraWidget


@pytest.fixture
def view():
    """Create one isolated widget with a deterministic command transport."""
    ensure_app()
    widget = StereoFishCameraWidget()
    widget.commands = []
    widget.stream_client.send_command = lambda command: widget.commands.append(command) or True
    widget._fish_connection_available = True
    widget._stream_state = 'connected'
    yield widget
    widget.close()


def state(view, width=512, height=48, camera_on=False, **extra):
    """Announce capabilities using raw SBS dimensions, not display dimensions."""
    values = dict(type='node_state', protocol='stereo-relay-v1', camera_on=camera_on,
                  source_width=width, source_height=height, camera_epoch=0,
                  calibration_sha256=hashlib.sha256(npz_bytes()).hexdigest(),
                  resolution_options=[dict(width=512, height=48), dict(width=640, height=48)],
                  resolution_switch=True)
    values.update(extra)
    view._on_message(json.dumps(values))


def test_options_are_server_supplied_and_apply_changes_capture(view):
    """Do not send a display resize; wait for the exact request acknowledgement."""
    state(view)
    assert view.resolution_combo.count() == 2
    assert view.resolution_combo.currentData() == (512, 48)
    assert '256' in view.resolution_combo.itemText(0)
    view.resolution_combo.setCurrentIndex(1)
    assert view.resolution_apply_btn.isEnabled()
    view._apply_resolution()
    command = view.commands[-1].split()
    assert command[:3] == ['SET_RESOLUTION', '640', '48']
    assert not view.cam_btn.isEnabled() and not view.resolution_combo.isEnabled()
    state(view)  # An unrelated/old status is not an acknowledgement.
    assert not view.cam_btn.isEnabled()
    state(view, width=640, command='SET_RESOLUTION', request_id=command[3])
    assert view._resolution_pending is None
    assert view._source_descriptor['width'] == 640
    assert view.cam_btn.isEnabled() and not view.resolution_apply_btn.isEnabled()


@pytest.mark.parametrize('on,recording', [(True, False), (False, True)])
def test_resolution_change_is_blocked_during_capture_or_recording(view, on, recording):
    """Changing dimensions must never silently reopen a camera or mix a recording."""
    state(view, camera_on=on)
    view.recording = recording
    view._apply_ui_state()
    view.resolution_combo.setCurrentIndex(1)
    view._apply_resolution()
    assert not view.commands
    assert not view.resolution_combo.isEnabled()
    view.recording = False


def test_legacy_service_is_preview_only_with_no_fake_modes(view):
    """An old server has no resolution-control capability, even if it streams stereo."""
    state(view, resolution_switch=False, resolution_options=[])
    assert not view.resolution_combo.isEnabled()
    assert not view.resolution_apply_btn.isEnabled()
    assert '升级' in view.resolution_hint.text()


def test_rejected_request_and_timeout_recover_from_actual_state(view):
    """Failure reverts the selected mode; a timeout queries but never retries the write."""
    state(view)
    view.resolution_combo.setCurrentIndex(1)
    view._apply_resolution()
    request = view.commands[-1].split()[-1]
    view._on_message(json.dumps(dict(type='error', command='SET_RESOLUTION',
                                    request_id=request, message='busy')))
    assert view._resolution_pending is None
    assert view.resolution_combo.currentData() == (512, 48)
    view.resolution_combo.setCurrentIndex(1)
    view._apply_resolution()
    request = view._resolution_pending['id']
    view._resolution_timeout(request)
    assert view.commands[-1] == 'GET_STATE'
    assert not view.cam_btn.isEnabled()
    state(view, width=640)
    assert view._resolution_pending is None and view.cam_btn.isEnabled()


def test_disconnect_clears_capabilities_and_old_timeout_is_ignored(view):
    """No stale resolution options or timer can apply to the next connection."""
    state(view)
    view.resolution_combo.setCurrentIndex(1)
    view._apply_resolution()
    request = view._resolution_pending['id']
    view._reset_remote_state()
    view._resolution_timeout(request)
    assert view._resolution_pending is None and view.commands[-1].startswith('SET_RESOLUTION')
    assert view.resolution_combo.count() == 0 and not view.resolution_combo.isEnabled()


def test_size_mismatch_previews_single_eye_without_wrong_distance(view, tmp_path):
    """Different capture size invalidates old calibration and points, not video preview."""
    state(view)
    blob = npz_bytes()
    view._on_calibration(dict(connection_id=view.stream_client.connection_id,
                             sha256=hashlib.sha256(blob).hexdigest(), bytes=len(blob)), blob)
    assert view._local_model is not None
    view._selected_point = (220, 20)
    state(view, width=640, camera_on=True)
    assert view._local_model is None and view._selected_point is None
    assert not view.range_btn.isEnabled()
    model = view.worker.model
    pair = np.zeros((48, 640, 3), np.uint8)
    pair[:, :320] = (0, 180, 0)
    pair[:, 320:] = (180, 0, 0)
    ok, jpeg = cv2.imencode('.jpg', pair)
    assert ok
    result = model.process_jpeg(jpeg.tobytes(), dict(frame_id=9,
        calibration_sha256=hashlib.sha256(blob).hexdigest()), True)
    assert result['image'].shape == (48, 320, 3)
    assert result['disparity'] is None and result['uncalibrated']
    view._local_result = result
    view._render_local_result(record=True)
    path = str(tmp_path/'one-eye.png')
    assert view.save_snapshot(path) == path
    assert cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR).shape == (320, 48, 3)
    assert view.distance_label.text().endswith('--')


def test_invalid_or_mono_like_capabilities_are_not_accepted(view):
    """Reject bad bounds, booleans, odd widths, duplicates and excessive option counts."""
    state(view, resolution_options=[dict(width=True, height=48), dict(width=513, height=48),
        dict(width=512, height=48), dict(width=512, height=48), dict(width=99999, height=10)])
    assert view.resolution_combo.count() == 1
    assert not view.resolution_apply_btn.isEnabled()


def test_return_to_calibrated_size_restores_model_and_clears_stale_points(view):
    """The cached original NPZ becomes usable again after changing back, without reload."""
    blob = npz_bytes()
    state(view)
    view._on_calibration(dict(connection_id=view.stream_client.connection_id,
                             sha256=hashlib.sha256(blob).hexdigest(), bytes=len(blob)), blob)
    state(view, width=640)
    assert view._local_model is None
    state(view, width=512)
    assert view._local_model is not None and view._selected_point is None
    assert view.current_frame is None


def test_invalid_source_disables_resolution_write_even_with_capabilities(view):
    """Incomplete server descriptors cannot authorize a resolution transaction."""
    state(view, width=513)
    assert view._source_descriptor is None
    assert not view.resolution_combo.isEnabled() and not view.resolution_apply_btn.isEnabled()


def test_pending_write_blocks_npz_and_old_camera_epoch(view, tmp_path):
    """In-flight calibration/old frames must not race the capture-size transaction."""
    state(view)
    view.resolution_combo.setCurrentIndex(1)
    view._apply_resolution()
    assert not view.load_npz_btn.isEnabled()
    assert not view.load_calibration_file(str(tmp_path/'any.npz'))
    assert '确认' in view.calibration_status_label.text()
    request = view.commands[-1].split()[-1]
    state(view, width=640, camera_on=True, camera_epoch=3,
          command='SET_RESOLUTION', request_id=request)
    submitted = []
    view.worker.submit = lambda metadata, jpeg: submitted.append(metadata)
    for epoch in (2, 3):
        view._submit_stereo(dict(connection_id=view.stream_client.connection_id,
                                 camera_epoch=epoch), b'jpeg')
    assert len(submitted) == 1 and submitted[0]['camera_epoch'] == 3


def test_camera_off_clears_running_text_and_distance(view):
    """A stopped stream must not keep presenting the last frame as active ranging."""
    state(view, camera_on=True)
    view.ranging_on = True
    view.range_state_label.setText('本地测距: 开')
    view.distance_label.setText('距离 D: 25cm')
    state(view)
    assert not view.ranging_on and view.distance_label.text().endswith('--')
    assert '已关闭' in view.range_state_label.text()
