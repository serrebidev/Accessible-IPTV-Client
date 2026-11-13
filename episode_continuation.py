"""Conservative episode ordering and natural-end detection."""
import playback_resume


def following_item(current, episodes):
    key = playback_resume.item_key(current)
    if not key:
        return None
    positions = [index for index, item in enumerate(episodes) if playback_resume.item_key(item) == key]
    if len(positions) != 1 or positions[0] + 1 >= len(episodes):
        return None
    following = episodes[positions[0] + 1]
    if (not playback_resume.item_key(following) or playback_resume.item_key(following) == key
            or following.get("provider-id") != current.get("provider-id")
            or following.get("playlist-id") != current.get("playlist-id")
            or following.get("series_id") != current.get("series_id")):
        return None
    # Duplicate episode identities are ambiguous even when adjacent rows differ.
    target = playback_resume.item_key(following)
    if sum(playback_resume.item_key(item) == target for item in episodes) != 1:
        return None
    return dict(following)


def natural_end(kind, seen_playing, manual_stop, position, length):
    return (kind == "vod" and seen_playing and not manual_stop
            and type(position) is int and type(length) is int and length > 0
            and length - min(2500, length // 20) <= position <= length + 1000)
