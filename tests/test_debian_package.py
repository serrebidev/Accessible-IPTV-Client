"""Structural tests for the Debian package built by tools/build_deb.py.

These run everywhere, including Windows, because the builder can assemble the
``ar`` archive without dpkg-deb. Only the archive layout and metadata are
checked here; whether the package installs and starts is covered by
tools/deb_smoke_test.sh in CI, which needs a real Debian system.
"""

import io
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def read_ar(path):
    """Return ``{member name: bytes}`` for a (small) ar archive."""
    data = path.read_bytes()
    assert data.startswith(b"!<arch>\n"), "not an ar archive"
    offset = 8
    members = {}
    order = []
    while offset + 60 <= len(data):
        header = data[offset:offset + 60]
        name = header[0:16].decode("ascii").strip()
        size = int(header[48:58].decode("ascii").strip())
        start = offset + 60
        members[name] = data[start:start + size]
        order.append(name)
        offset = start + size + (size % 2)
    members["__order__"] = order
    return members


@pytest.fixture(scope="module")
def built_package(tmp_path_factory):
    output_dir = tmp_path_factory.mktemp("deb")
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "build_deb.py"),
         "--no-dpkg", "--output-dir", str(output_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"build_deb.py failed:\n{result.stdout}\n{result.stderr}"
    packages = list(output_dir.glob("accessible-iptv-client_*_all.deb"))
    assert len(packages) == 1, f"expected exactly one .deb, got {packages}"
    return packages[0]


@pytest.fixture(scope="module")
def members(built_package):
    return read_ar(built_package)


@pytest.fixture(scope="module")
def data_entries(members):
    with tarfile.open(fileobj=io.BytesIO(members["data.tar.gz"]), mode="r:gz") as tar:
        return {info.name.lstrip("./"): info for info in tar.getmembers()}


@pytest.fixture(scope="module")
def control(members):
    with tarfile.open(fileobj=io.BytesIO(members["control.tar.gz"]), mode="r:gz") as tar:
        handle = tar.extractfile("./control")
        assert handle is not None
        return handle.read().decode("utf-8")


def test_archive_has_the_three_members_dpkg_expects_in_order(members):
    assert members["__order__"] == ["debian-binary", "control.tar.gz", "data.tar.gz"]
    assert members["debian-binary"] == b"2.0\n"


def test_control_declares_the_runtime_dependencies(control):
    assert "Package: accessible-iptv-client\n" in control
    assert "Architecture: all\n" in control
    for dependency in ("python3-wxgtk4.0", "python3-vlc", "vlc-plugin-base", "ffmpeg"):
        assert dependency in control, f"{dependency} missing from Depends"
    # Casting packages are deliberately absent: Debian's pychromecast is too old
    # and pyatv is unpackaged, so casting.py has to degrade instead.
    assert "pyatv" not in control.split("Description:")[0]


def test_control_version_matches_app_meta(control, built_package):
    import app_meta

    assert f"Version: {app_meta.APP_VERSION}-1\n" in control
    assert built_package.name == f"accessible-iptv-client_{app_meta.APP_VERSION}-1_all.deb"


def test_payload_ships_the_app_and_every_catalogue(data_entries):
    assert "usr/lib/accessible-iptv-client/main.py" in data_entries
    assert "usr/lib/accessible-iptv-client/sitecustomize.py" in data_entries
    catalogues = [name for name in data_entries if name.endswith("iptvclient.mo")]
    assert len(catalogues) >= 13, f"expected a catalogue per language, got {catalogues}"


def test_payload_omits_windows_only_files(data_entries):
    for name in data_entries:
        assert not name.endswith((".exe", ".bat", ".ps1", ".spec")), f"{name} should not ship on Debian"


def test_launcher_desktop_entry_and_man_page_are_installed(data_entries):
    launcher = data_entries["usr/bin/accessible-iptv-client"]
    assert launcher.mode == 0o755, "the launcher must be executable"
    assert data_entries["usr/share/applications/accessible-iptv-client.desktop"].mode == 0o644
    assert "usr/share/man/man1/accessible-iptv-client.1.gz" in data_entries
    assert "usr/share/doc/accessible-iptv-client/copyright" in data_entries
    assert "usr/share/doc/accessible-iptv-client/changelog.Debian.gz" in data_entries


def test_payload_is_owned_by_root_with_a_plausible_timestamp(data_entries):
    for name, info in data_entries.items():
        assert info.uid == 0 and info.gid == 0, f"{name} is not root-owned"
        # A zeroed mtime trips lintian's package-contains-ancient-file check.
        assert info.mtime > 1_600_000_000, f"{name} has an implausible mtime"


def test_md5sums_cover_every_regular_file(members, data_entries):
    with tarfile.open(fileobj=io.BytesIO(members["control.tar.gz"]), mode="r:gz") as tar:
        handle = tar.extractfile("./md5sums")
        assert handle is not None
        listed = {line.split("  ", 1)[1] for line in handle.read().decode("utf-8").splitlines()}
    files = {name for name, info in data_entries.items() if info.isfile()}
    assert listed == files
