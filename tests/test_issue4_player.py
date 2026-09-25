import types

from internal_player import InternalPlayerFrame


def test_subtitle_tracks_decode_names_and_include_off_choice():
    player = types.SimpleNamespace(
        video_get_spu_description=lambda: [(-1, b"Disable"), (2, "English".encode())],
        video_get_spu=lambda: -1,
        video_set_spu=lambda track_id: 0,
    )
    frame = types.SimpleNamespace(player=player,
                                  _decode_track_name=InternalPlayerFrame._decode_track_name,
                                  _subtitle_tracks=lambda: [])
    tracks = InternalPlayerFrame._subtitle_tracks(frame)
    assert tracks == [(-1, "Disable"), (2, "English")]


def test_announcement_level_suppresses_automatic_status(monkeypatch):
    events = []
    label = types.SimpleNamespace(value="", GetLabel=lambda: label.value,
                                  SetLabel=lambda value: setattr(label, "value", value))
    frame = types.SimpleNamespace(
        _last_bitrate_mbps=None, _last_buffer_seconds=2.0, _volume_value=50,
        _last_status_prefix="", _audio_track_label="", status_label=label,
        announcement_level=1, _speak=events.append)
    InternalPlayerFrame._update_status_label(frame, "Buffering", priority=3)
    assert not events
    InternalPlayerFrame._update_status_label(frame, "Stream lost", priority=1)
    assert len(events) == 1
