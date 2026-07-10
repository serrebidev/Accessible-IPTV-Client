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

## Output

Release mode prepends the generated release notes to [`CHANGELOG.md`](CHANGELOG.md), builds the PyInstaller app, signs the executable, writes the update manifest, pushes the version commit and tag, and creates the GitHub release assets under `dist\release`.
