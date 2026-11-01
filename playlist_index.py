"""Optional compact indexes for playlist navigation and search."""

from __future__ import annotations

from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence


class PlaylistIndex:
    """Reuse playlist order, normalized names, and scope/group membership.

    The index stores references to the existing channel dictionaries rather
    than copying them. It is deliberately independent of wx and can be
    discarded whenever the playlist model is replaced.
    """

    def __init__(
        self,
        all_channels: List[Dict[str, str]],
        channels_by_group: Mapping[str, Sequence[Dict[str, str]]],
    ):
        self.channels = all_channels
        self._normalized_names = {
            id(channel): (channel.get("name") or "").lower()
            for channel in all_channels
        }
        self._scope_channels: Dict[str, List[Dict[str, str]]] = {}
        self._scope_groups: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
        self._all_groups: Dict[str, List[Dict[str, str]]] = {}
        for channel in all_channels:
            scope = str(channel.get("playlist-id") or "")
            self._scope_channels.setdefault(scope, []).append(channel)
        for group, channels in channels_by_group.items():
            for channel in channels:
                scope = str(channel.get("playlist-id") or "")
                self._scope_groups.setdefault(scope, {}).setdefault(group, []).append(channel)

    def normalized_name(self, channel: Dict[str, str]) -> str:
        """Return the cached search name, tolerating an uncached row."""
        return self._normalized_names.get(id(channel), (channel.get("name") or "").lower())

    def all_for_scope(self, scope: str) -> List[Dict[str, str]]:
        if not scope:
            return self.channels
        return self._scope_channels.get(scope, [])

    def groups_for_scope(self, scope: str) -> Dict[str, List[Dict[str, str]]]:
        if not scope:
            # The caller owns the original all-playlists mapping and can use
            # it without copying.
            return self._all_groups
        return self._scope_groups.get(scope, {})

    def set_all_groups(self, groups: Dict[str, List[Dict[str, str]]]) -> None:
        """Attach the original all-playlists mapping without copying it."""
        self._all_groups = groups

    def search(
        self,
        channels: Iterable[Dict[str, str]],
        query: str,
        is_current: Optional[Callable[[], bool]] = None,
    ) -> List[Dict[str, str]]:
        matches = []
        for position, channel in enumerate(channels):
            if position % 256 == 0 and is_current is not None and not is_current():
                return []
            if query in self.normalized_name(channel):
                matches.append(channel)
        return matches
