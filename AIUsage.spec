# PyInstaller build spec for AIUsage.
#
# Build with:   py -m PyInstaller --noconfirm AIUsage.spec
# or just run:  build-exe.bat
#
# Produces one windowed, self-contained dist\AIUsage.exe - no Python and no
# packages needed on the machine that runs it.

block_cipher = None

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    # config.example.json travels inside the exe; app.py writes a real
    # config.json next to the exe on first run if one is missing.
    datas=[('config/config.example.json', 'config')],
    hiddenimports=[
        # Imported through the package, not directly by app.py.
        'usage_service.providers',
        'usage_service.server',
        'usage_service.monitor',
        'widget.widget',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Nothing here is used; leaving them out keeps the exe smaller.
    excludes=[
        'unittest', 'pydoc', 'doctest', 'pdb',
        'email', 'http', 'xml', 'xmlrpc',
        'sqlite3', 'ssl', 'lib2to3', 'distutils', 'setuptools', 'pip',
        'test', 'multiprocessing',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AIUsage',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no command prompt window - this is a GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',      # drop an icon.ico next to this file and uncomment
)
