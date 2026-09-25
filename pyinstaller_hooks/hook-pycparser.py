# pycparser 3.0 dropped the generated lextab/yacctab modules that the
# pyinstaller-hooks-contrib hook still lists, so PyInstaller warned they were
# missing. This hook takes precedence and asks for nothing.
hiddenimports = []
