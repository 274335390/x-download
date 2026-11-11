'use strict';

// Processing stays inside browser workers; no media is uploaded to this site.
window.BrowserMedia = (() => {
  const MAX_BYTES = 256 * 1024 * 1024;
  const TIMEOUT = 10 * 60 * 1000;
  let ffmpegScript = null, converting = false, packing = false;

  function loadFFmpeg() {
    if (window.FFmpegWASM) return Promise.resolve();
    if (ffmpegScript) return ffmpegScript;
    ffmpegScript = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      const finish = error => {
        clearTimeout(timer);
        script.onload = script.onerror = null;
        if (error) { script.remove(); reject(Error('conversionError')); }
        else resolve();
      };
      const timer = setTimeout(() => finish(true), 60000);
      script.src = '/vendor/ffmpeg.js';
      script.onload = () => finish(!window.FFmpegWASM);
      script.onerror = () => finish(true);
      document.head.append(script);
    }).catch(error => { ffmpegScript = null; throw error; });
    return ffmpegScript;
  }

  // ZIP_STORED avoids wasting CPU recompressing already compressed media.
  // The worker streams Blob chunks, keeping CRC work off the UI thread.
  function zipWorker() {
    self.onmessage = async ({ data: { entries, library, maxBytes } }) => {
      try {
        importScripts(library);
        const total = entries.reduce((sum, entry) => sum + entry.blob.size, 0);
        let received = 0, emitted = 0;
        const zip = new fflate.Zip((error, chunk, final) => {
          if (error) throw error;
          emitted += chunk.byteLength;
          if (emitted > maxBytes) throw Error('sizeError');
          self.postMessage({ chunk, final }, [chunk.buffer]);
        });
        for (const { name, blob } of entries) {
          const file = new fflate.ZipPassThrough(name);
          zip.add(file);
          const reader = blob.stream().getReader();
          try {
            while (true) {
              const { value, done } = await reader.read();
              if (done) break;
              received += value.byteLength;
              file.push(value, false);
              self.postMessage({ progress: total ? Math.min(99, received / total * 100) : 0 });
            }
          } finally { reader.releaseLock(); }
          file.push(new Uint8Array(), true);
        }
        zip.end();
      } catch (error) {
        self.postMessage({ error: error.message === 'sizeError' ? 'sizeError' : 'downloadError' });
      }
    };
  }

  async function pack(entries, onProgress = () => {}, signal) {
    if (signal?.aborted) throw Error('cancelled');
    if (packing) throw Error('busyError');
    if (!Array.isArray(entries) || !entries.length || entries.length > 10 ||
        entries.some(entry => !/^[A-Za-z0-9._-]+$/.test(entry.name) || !(entry.blob instanceof Blob)) ||
        new Set(entries.map(entry => entry.name)).size !== entries.length) throw Error('invalidSelection');
    if (entries.reduce((sum, entry) => sum + entry.blob.size, 0) > MAX_BYTES) throw Error('sizeError');
    packing = true;
    let worker, workerURL, timer, onAbort;
    try {
      workerURL = URL.createObjectURL(new Blob(['(', zipWorker.toString(), ')();'], { type: 'text/javascript' }));
      worker = new Worker(workerURL);
      return await new Promise((resolve, reject) => {
        const chunks = [];
        onAbort = () => {
          worker.terminate();
          chunks.length = 0;
          reject(Error('cancelled'));
        };
        signal?.addEventListener('abort', onAbort, { once: true });
        if (signal?.aborted) { onAbort(); return; }
        timer = setTimeout(() => reject(Error('downloadError')), TIMEOUT);
        worker.onerror = () => reject(Error('downloadError'));
        worker.onmessage = ({ data }) => {
          if (signal?.aborted) return;
          if (data.error) { reject(Error(data.error)); return; }
          if (data.chunk) chunks.push(data.chunk);
          if (data.progress !== undefined) onProgress(data.progress);
          if (data.final) { onProgress(100); resolve(new Blob(chunks, { type: 'application/zip' })); }
        };
        worker.postMessage({ entries, library: new URL('/vendor/fflate.min.js', location.href).href, maxBytes: MAX_BYTES });
      });
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      if (worker) worker.onmessage = worker.onerror = null;
      worker?.terminate();
      if (workerURL) URL.revokeObjectURL(workerURL);
      packing = false;
    }
  }

  async function convert(blob, mode, onProgress = () => {}, signal) {
    if (signal?.aborted) throw Error('cancelled');
    if (converting) throw Error('busyError');
    if (!(blob instanceof Blob) || !['mp3', 'gif'].includes(mode)) throw Error('invalidSelection');
    if (blob.size > MAX_BYTES) throw Error('sizeError');
    converting = true;
    let ffmpeg, timer, onAbort, stopped = false;
    const errors = [];
    const checkActive = () => {
      if (signal?.aborted) throw Error('cancelled');
      if (stopped) throw Error('conversionError');
    };
    try {
      const interrupted = new Promise((_, reject) => {
        onAbort = () => {
          stopped = true;
          ffmpeg?.terminate();
          reject(Error('cancelled'));
        };
        signal?.addEventListener('abort', onAbort, { once: true });
        if (signal?.aborted) { onAbort(); return; }
        timer = setTimeout(() => {
          stopped = true;
          ffmpeg?.terminate();
          reject(Error('conversionError'));
        }, TIMEOUT);
      });
      return await Promise.race([
        (async () => {
          checkActive();
          await loadFFmpeg();
          checkActive();
          ffmpeg = new FFmpegWASM.FFmpeg();
          ffmpeg.on('log', ({ message }) => { errors.push(message); if (errors.length > 16) errors.shift(); });
          ffmpeg.on('progress', ({ progress }) => {
            if (!stopped && !signal?.aborted && Number.isFinite(progress)) onProgress(Math.max(0, Math.min(99, progress * 100)));
          });
          await ffmpeg.load({
            coreURL: new URL('/vendor/ffmpeg-core.js', location.href).href,
            wasmURL: new URL('/vendor/ffmpeg-core.wasm', location.href).href
          });
          checkActive();
          const input = new Uint8Array(await blob.arrayBuffer());
          checkActive();
          await ffmpeg.writeFile('input.mp4', input);
          checkActive();
          const output = 'output.' + mode;
          const args = ['-hide_banner', '-loglevel', 'error', '-i', 'input.mp4'];
          if (mode === 'mp3') args.push('-map', '0:a:0', '-vn', '-codec:a', 'libmp3lame', '-q:a', '2', '-f', 'mp3');
          else args.push('-t', '120', '-filter_complex', 'fps=12,scale=640:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer', '-loop', '0', '-f', 'gif');
          const result = await ffmpeg.exec([...args, '-fs', String(MAX_BYTES), output], TIMEOUT);
          checkActive();
          if (result !== 0) throw Error(/matches no streams|does not contain any stream/.test(errors.join('\n')) ? 'noAudio' : 'conversionError');
          const data = await ffmpeg.readFile(output);
          checkActive();
          if (!data.byteLength) throw Error('conversionError');
          // -fs may stop writing successfully: never offer a truncated output as complete.
          if (data.byteLength >= MAX_BYTES) throw Error('sizeError');
          const converted = new Blob([data], { type: mode === 'mp3' ? 'audio/mpeg' : 'image/gif' });
          onProgress(100);
          return converted;
        })(),
        interrupted
      ]);
    } catch (error) {
      if (signal?.aborted) throw Error('cancelled');
      throw Error(['cancelled', 'noAudio', 'sizeError'].includes(error?.message) ? error.message : 'conversionError');
    } finally {
      stopped = true;
      clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      // Terminating the worker releases the core and its entire virtual filesystem.
      ffmpeg?.terminate();
      converting = false;
    }
  }

  return { pack, convert };
})();
