/**
 * static/pgs-decoder.js — Blu-ray PGS (.sup / hdmv_pgs_subtitle) HTML5 Canvas Decoder
 * Decodes raw binary Presentation Graphic Streams (PCS, PDS, ODS) into canvas bitmaps
 * with frame-perfect timestamps, YUV->RGB palette translation, and RLE bitmap decompression.
 * Enables zero-transcode, zero-server-overhead Blu-ray graphical subtitles in HTML5 browsers.
 */

class EvoPgsDecoder {
  constructor() {
    this.cues = [];
    this.videoEl = null;
    this.canvasEl = null;
    this.ctx = null;
    this.activeCue = null;
    this._timeUpdateHandler = this._onTimeUpdate.bind(this);
    this._seekHandler = this._onSeek.bind(this);
  }

  /**
   * Parses binary .sup ArrayBuffer into an array of timed PGS graphical cues.
   * @param {ArrayBuffer} arrayBuffer
   * @returns {Array} Array of cue objects
   */
  parse(arrayBuffer) {
    const bytes = new Uint8Array(arrayBuffer);
    const view = new DataView(arrayBuffer);
    const len = bytes.length;
    let offset = 0;

    let currentPcs = null;
    let currentPalette = null;
    let currentOds = null;
    const cues = [];

    while (offset + 13 <= len) {
      // Synchronize to 'PG' magic bytes (0x50, 0x47)
      if (bytes[offset] !== 0x50 || bytes[offset + 1] !== 0x47) {
        offset++;
        continue;
      }

      const pts = view.getUint32(offset + 2) / 90000;
      const type = bytes[offset + 10];
      const segLen = view.getUint16(offset + 11);
      const dataOffset = offset + 13;

      if (dataOffset + segLen > len) break;

      switch (type) {
        case 0x16: { // PCS: Presentation Composition Segment
          const videoWidth = view.getUint16(dataOffset);
          const videoHeight = view.getUint16(dataOffset + 2);
          const compState = bytes[dataOffset + 7];
          const numObjects = bytes[dataOffset + 10];

          if (numObjects > 0) {
            currentPcs = {
              pts,
              videoWidth,
              videoHeight,
              x: view.getUint16(dataOffset + 15),
              y: view.getUint16(dataOffset + 17),
            };
          } else {
            // Screen clear signal: closes the previous active cue
            if (cues.length > 0 && !cues[cues.length - 1].end) {
              cues[cues.length - 1].end = pts;
            }
            currentPcs = null;
            currentOds = null;
          }
          break;
        }

        case 0x14: { // PDS: Palette Definition Segment
          currentPalette = this._parsePalette(bytes, dataOffset, segLen);
          break;
        }

        case 0x15: { // ODS: Object Definition Segment
          if (segLen >= 11) {
            const width = view.getUint16(dataOffset + 7);
            const height = view.getUint16(dataOffset + 9);
            const rleData = bytes.subarray(dataOffset + 11, dataOffset + segLen);
            currentOds = { width, height, rleData };
          }
          break;
        }

        case 0x80: { // END: End of Display Set
          if (currentPcs && currentOds && currentPalette) {
            // Close previous cue if still open
            if (cues.length > 0 && !cues[cues.length - 1].end) {
              cues[cues.length - 1].end = currentPcs.pts;
            }

            const rawRgba = this._decodeRle(currentOds.rleData, currentOds.width, currentOds.height, currentPalette);
            cues.push({
              start: currentPcs.pts,
              end: null, // Will be resolved by next PCS clear or next cue start
              x: currentPcs.x,
              y: currentPcs.y,
              width: currentOds.width,
              height: currentOds.height,
              videoWidth: currentPcs.videoWidth || 1920,
              videoHeight: currentPcs.videoHeight || 1080,
              rawRgba,
            });
          }
          break;
        }
      }

      offset = dataOffset + segLen;
    }

    // Default duration clamp for final trailing cue (5 seconds fallback)
    for (let i = 0; i < cues.length; i++) {
      if (!cues[i].end) {
        cues[i].end = (i + 1 < cues.length) ? cues[i + 1].start : cues[i].start + 5.0;
      }
    }

    this.cues = cues;
    return cues;
  }

  /**
   * Decodes YCbCr + Alpha palette entries into 32-bit RGBA lookup table.
   */
  _parsePalette(bytes, offset, len) {
    const palette = new Array(256);
    // Initialize full transparency
    for (let i = 0; i < 256; i++) {
      palette[i] = [0, 0, 0, 0];
    }

    let ptr = offset + 2; // Skip palette_id and palette_version
    const end = offset + len;

    while (ptr + 5 <= end) {
      const id = bytes[ptr];
      const y = bytes[ptr + 1];
      const cr = bytes[ptr + 2];
      const cb = bytes[ptr + 3];
      const a = bytes[ptr + 4];

      // Standard ITU-R BT.601 YCbCr to sRGB conversion
      const r = Math.max(0, Math.min(255, Math.round(y + 1.402 * (cr - 128))));
      const g = Math.max(0, Math.min(255, Math.round(y - 0.344136 * (cb - 128) - 0.714136 * (cr - 128))));
      const b = Math.max(0, Math.min(255, Math.round(y + 1.772 * (cb - 128))));

      palette[id] = [r, g, b, a];
      ptr += 5;
    }

    return palette;
  }

  /**
   * Decompresses Blu-ray run-length encoded (RLE) bitmap pixels.
   */
  _decodeRle(rleBytes, width, height, palette) {
    const totalPixels = width * height;
    const rgba = new Uint8ClampedArray(totalPixels * 4);
    let inPtr = 0;
    let outPixel = 0;

    const rleLen = rleBytes.length;

    while (inPtr < rleLen && outPixel < totalPixels) {
      const byte1 = rleBytes[inPtr++];
      if (byte1 !== 0) {
        // Single non-zero pixel
        const [r, g, b, a] = palette[byte1] || [0, 0, 0, 0];
        const idx = outPixel * 4;
        rgba[idx] = r;
        rgba[idx + 1] = g;
        rgba[idx + 2] = b;
        rgba[idx + 3] = a;
        outPixel++;
      } else {
        // Zero marker: flags determine run-length or end-of-line
        if (inPtr >= rleLen) break;
        const flags = rleBytes[inPtr++];
        if (flags === 0) {
          // End of scanline marker
          const lineRemainder = outPixel % width;
          if (lineRemainder !== 0) {
            outPixel += (width - lineRemainder);
          }
        } else {
          let runLength = 0;
          let colorId = 0;

          if (flags < 0x40) {
            // Short run of color 0
            runLength = flags;
            colorId = 0;
          } else if (flags < 0x80) {
            // Long run of color 0
            if (inPtr >= rleLen) break;
            runLength = ((flags & 0x3f) << 8) | rleBytes[inPtr++];
            colorId = 0;
          } else if (flags < 0xc0) {
            // Short run of specific color
            if (inPtr >= rleLen) break;
            runLength = flags & 0x3f;
            colorId = rleBytes[inPtr++];
          } else {
            // Long run of specific color
            if (inPtr + 1 >= rleLen) break;
            runLength = ((flags & 0x3f) << 8) | rleBytes[inPtr++];
            colorId = rleBytes[inPtr++];
          }

          const [r, g, b, a] = palette[colorId] || [0, 0, 0, 0];
          for (let k = 0; k < runLength && outPixel < totalPixels; k++) {
            const idx = outPixel * 4;
            rgba[idx] = r;
            rgba[idx + 1] = g;
            rgba[idx + 2] = b;
            rgba[idx + 3] = a;
            outPixel++;
          }
        }
      }
    }

    return rgba;
  }

  /**
   * Attaches the decoder to a video element and target canvas overlay.
   */
  attach(videoEl, canvasEl) {
    this.detach();
    this.videoEl = videoEl;
    this.canvasEl = canvasEl;
    if (!videoEl || !canvasEl) return;

    this.ctx = canvasEl.getContext('2d');
    canvasEl.classList.remove('hidden');

    videoEl.addEventListener('timeupdate', this._timeUpdateHandler);
    videoEl.addEventListener('seeked', this._seekHandler);
    this._renderAtTime(videoEl.currentTime);
  }

  /**
   * Detaches and clears the canvas overlay.
   */
  detach() {
    if (this.videoEl) {
      this.videoEl.removeEventListener('timeupdate', this._timeUpdateHandler);
      this.videoEl.removeEventListener('seeked', this._seekHandler);
      this.videoEl = null;
    }
    if (this.canvasEl && this.ctx) {
      this.ctx.clearRect(0, 0, this.canvasEl.width, this.canvasEl.height);
      this.canvasEl.classList.add('hidden');
      this.canvasEl = null;
      this.ctx = null;
    }
    this.activeCue = null;
  }

  _onTimeUpdate() {
    if (!this.videoEl) return;
    this._renderAtTime(this.videoEl.currentTime);
  }

  _onSeek() {
    if (!this.videoEl) return;
    this._renderAtTime(this.videoEl.currentTime);
  }

  _renderAtTime(currentTime) {
    if (!this.ctx || !this.canvasEl) return;

    // Binary search / scan for matching cue
    const cue = this.cues.find((c) => c.start <= currentTime && currentTime <= c.end);

    if (cue === this.activeCue) return; // Already painted

    this.activeCue = cue;

    if (!cue) {
      this.ctx.clearRect(0, 0, this.canvasEl.width, this.canvasEl.height);
      return;
    }

    // Set canvas dimensions to match the authoring video resolution
    if (this.canvasEl.width !== cue.videoWidth || this.canvasEl.height !== cue.videoHeight) {
      this.canvasEl.width = cue.videoWidth;
      this.canvasEl.height = cue.videoHeight;
    } else {
      this.ctx.clearRect(0, 0, this.canvasEl.width, this.canvasEl.height);
    }

    // Cache ImageData on cue to avoid repeated buffer copies
    if (!cue._cachedImageData) {
      cue._cachedImageData = new ImageData(cue.rawRgba, cue.width, cue.height);
    }

    this.ctx.putImageData(cue._cachedImageData, cue.x, cue.y);
  }
}

// Global instance for browser player integration
window.evoPgsDecoder = new EvoPgsDecoder();
