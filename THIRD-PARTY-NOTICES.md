# Browser processing dependencies

The application's own code is MIT licensed. The following unmodified third-party
programs retain their respective licenses; the bundled FFmpeg core is **not MIT**.

| Component | Pinned version | License | Local license text |
| --- | --- | --- | --- |
| `@ffmpeg/ffmpeg` JavaScript wrapper | 0.12.15 | MIT, copyright 2019 Jerome Wu | [MIT](licenses/browser-ffmpeg-MIT.txt) |
| `@ffmpeg/core` single-thread WebAssembly build | 0.12.10 | GPL-2.0-or-later, including its linked libraries under their respective terms | [GPL v2](licenses/browser-ffmpeg-core-GPLv2.txt) |
| `fflate` | 0.8.3 | MIT, copyright 2026 Arjun Barrett | [MIT](licenses/browser-fflate-MIT.txt) |

Versions, official npm download locations and SHA-512 integrity values are in
[web/vendor-manifest.json](web/vendor-manifest.json). Run
`pwsh -File scripts/fetch-browser-vendor.ps1` to restore the browser runtime. This
does not execute npm installation scripts. Generated `web/vendor/` files are
excluded from Git by the existing `vendor/` ignore rule; deploy the restored
directory alongside `web/`. The application loads the ZIP library only for ZIP
creation and the approximately 31 MiB FFmpeg core only for format conversion.

## Corresponding source and build instructions

The FFmpeg core 0.12.10 release comes from upstream commit
[`71aa99d37c02a7b4c435275ca9ef50e612f6efa1`](https://github.com/ffmpegwasm/ffmpeg.wasm/tree/71aa99d37c02a7b4c435275ca9ef50e612f6efa1).
The [source archive](https://github.com/ffmpegwasm/ffmpeg.wasm/archive/71aa99d37c02a7b4c435275ca9ef50e612f6efa1.tar.gz)
contains the wrapper source, core bindings, patches and build scripts. Its
[Dockerfile](https://github.com/ffmpegwasm/ffmpeg.wasm/blob/71aa99d37c02a7b4c435275ca9ef50e612f6efa1/Dockerfile)
records the source repositories and versions for FFmpeg and external libraries;
the [build directory](https://github.com/ffmpegwasm/ffmpeg.wasm/tree/71aa99d37c02a7b4c435275ca9ef50e612f6efa1/build)
contains their build commands. This is the single-thread core (`FFMPEG_ST`), not
`@ffmpeg/core-mt`.

The build uses FFmpeg n5.1.4 and GPL components such as x264 and x265. Its complete
source includes the external library sources identified by that Dockerfile, not
only the npm package or JavaScript wrapper. [FFmpeg source](https://github.com/FFmpeg/FFmpeg/tree/n5.1.4)
and [fflate source](https://github.com/101arrowz/fflate/tree/v0.8.3) are also available
upstream. If redistributing the core binary, preserve these notices and license
texts and supply corresponding source as required by the GPL. Do not relabel the
core or its linked libraries as MIT.

No modifications are made to the vendored npm distribution files. The downloader
and installer use them as separate browser processing components.
