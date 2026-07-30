# Accessible IPTV Client Build and Release

Use the checked-in batch files for all Windows builds and releases.

## Commands

```bat
build.bat build
build.bat dry-run
build.bat release
```

`build.bat` delegates to `build_exe.bat`, and `build_exe.bat` delegates release behavior to `tools\release.py`.

## Release Rules

- Release from `main`.
- Use `build.bat release` for official Windows releases.
- GitHub releases must be published, never drafts.
- The release script explicitly marks the new release as latest and non-draft.
- The release script removes any remaining draft releases after publishing.
- Do not ship if the build shows unresolved warnings, errors, or dependency mismatches.

## Debian package

The `.deb` is not built by `build.bat`; it is built by the **Debian Package** GitHub Actions workflow ([`.github/workflows/debian-package.yml`](.github/workflows/debian-package.yml)):

- every push to `main` builds the package and uploads it as a workflow artifact,
- publishing a release (or running the workflow manually against a tag) also attaches `accessible-iptv-client_<version>-1_all.deb` to that release.

The workflow builds with [`tools/build_deb.py`](tools/build_deb.py), gates on `lintian` errors, then installs the package in a `debian:trixie` container and asserts the app's window really maps under Xvfb ([`tools/deb_smoke_test.sh`](tools/deb_smoke_test.sh)).

To build one by hand — `dpkg-deb` is used when present, and the archive is assembled directly when it is not, so this also works on Windows:

```bash
python3 tools/build_deb.py                  # dist/release/accessible-iptv-client_<version>-1_all.deb
python3 tools/build_deb.py --version 1.2.3  # override the version from app_meta.py
```

The package is `Architecture: all` and runs the app with the system Python, so it depends on apt's `python3-wxgtk4.0`, `python3-vlc`, VLC plugins, and `ffmpeg` rather than bundling them. Nothing about it is signed — Authenticode signing applies to the Windows assets only.

## Output

Release mode prepends the generated release notes to [`CHANGELOG.md`](CHANGELOG.md), builds the PyInstaller app, signs the executable, writes the update manifest, pushes the version commit and tag, and creates the GitHub release assets under `dist\release`.
