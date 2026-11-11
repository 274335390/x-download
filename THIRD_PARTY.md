# Third-party components

Dongdong uses these independently maintained components. Availability of X and Instagram media depends on the upstream services and the user's network.

Browser ZIP and WebAssembly conversion use separately pinned dependencies. Their licenses, corresponding source and restoration instructions are in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

| Component | Use | License / source |
| --- | --- | --- |
| FxEmbed / FxTwitter public API | Public post metadata, video variants, GIF and photos | https://github.com/FxEmbed/FxEmbed (MIT); https://docs.fxembed.com/ |
| yt-dlp | X video/GIF and Instagram Reel extraction | Unlicense; https://github.com/yt-dlp/yt-dlp |
| Instaloader 4.16 | Public Instagram post and carousel metadata | MIT; https://github.com/instaloader/instaloader ; license in `licenses/Instaloader-MIT.txt` |
| FFmpeg | MP3 extraction and actual GIF encoding, separate subprocess | Bundled build: 7.1.1 essentials from https://www.gyan.dev/ffmpeg/builds/ ; GPLv3 build with third-party codecs. License and build README are in `licenses/`. FFmpeg source: https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz ; upstream build scripts and library source links are listed by the build provider. |
| Python | Runtime | PSF license; https://www.python.org/ |
| Flask / Werkzeug / Jinja / MarkupSafe / ItsDangerous / Click | Web interface and request handling | BSD-3-Clause; https://palletsprojects.com/ |
| Waitress | WSGI HTTP server | ZPL-2.1; https://github.com/Pylons/waitress |
| Requests / urllib3 / charset-normalizer / idna / certifi | HTTPS connections | Apache-2.0 / MIT / MIT / BSD-3-Clause / MPL-2.0; respective package metadata |
| pywebview / pythonnet / clr-loader | Windows WebView2 desktop window | BSD-3-Clause / MIT / MIT; https://github.com/r0x0r/pywebview ; https://github.com/pythonnet/pythonnet |
| Microsoft WebView2 Runtime | Native embedded browser supplied by Windows | Microsoft terms; https://developer.microsoft.com/microsoft-edge/webview2/ |
| PyInstaller | Windows packaging | GPL with bootloader exception; https://pyinstaller.org/ |

The main application is provided as editable source in the HTML/source bundle. Bundled third-party licenses remain applicable. Before publishing a binary distribution, retain the notices and satisfy the source-distribution obligations of its bundled GPL components. Neither free access nor voluntary donations alter upstream license terms.

X post identifiers are sent to FxTwitter, with yt-dlp as a fallback. Instagram post links are resolved through yt-dlp or Instaloader using anonymous sessions. Media comes from the corresponding platform's CDN. This version does not request account passwords or load browser login cookies. Browser mode fetches media on the user's device; desktop and optional server mode use the application's network connection.
