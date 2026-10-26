// Renders the moving CANvision eye as a looping GIF, assets/eye.gif, used on the title slide and on
// "The idea" slide. A GIF plays by itself in PowerPoint and in WPS, with no click and no custom
// animation. In one 6 second loop:
//   - the radar sweep turns once, clockwise;
//   - the red contact lights up when the beam crosses it, sends a ping ring and fades like radar
//     afterglow;
//   - a CAN_H pulse and a CAN_L pulse come in from the left together and ride over the upper and
//     under the lower lid as a mirrored pair, like the two wires of the bus carrying the same bit.
// Usage: node eye_gif.js   (needs sharp; FFMPEG may point at ffmpeg.exe if it is not on PATH)
const fs = require('fs');
const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');
const sharp = require('sharp');
const { eyeBase } = require('./hero.js');

// the colours of THEME in build.js
const HX = { dk1: '0A1420', lt1: 'FFFFFF', accent1: '2FF0D6', accent3: 'FF5A68', accent5: '6EA8FE' };
const FFMPEG = process.env.FFMPEG || 'ffmpeg';
const FPS = 25, LOOP = 6, N = FPS * LOOP, WIDTH = 900;

const g = eyeBase(HX);
const { PW, PH, cx, cy, R, L, Rc } = g;
const HEIGHT = Math.round(PH * WIDTH / PW);
const sized = (svg) => svg.replace(`width="${PW}" height="${PH}"`, `width="${WIDTH}" height="${HEIGHT}"`);

// a path made of straight lines and cubic Beziers, walked at constant speed
function walker(start, segs) {
  const pts = [start];
  let p = start;
  for (const s of segs) {
    if (s.length === 2) {
      for (let i = 1; i <= 200; i++) pts.push([p[0] + (s[0] - p[0]) * i / 200, p[1] + (s[1] - p[1]) * i / 200]);
      p = s;
    } else {
      const [x1, y1, x2, y2, x3, y3] = s;
      for (let i = 1; i <= 1000; i++) {
        const t = i / 1000, u = 1 - t;
        pts.push([u * u * u * p[0] + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t * t * t * x3,
          u * u * u * p[1] + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t * t * t * y3]);
      }
      p = [x3, y3];
    }
  }
  const acc = [0];
  for (let i = 1; i < pts.length; i++) acc.push(acc[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]));
  const total = acc[acc.length - 1];
  return (f) => {
    const want = f * total;
    let lo = 0, hi = acc.length - 1;
    while (hi - lo > 1) { const m = (lo + hi) >> 1; if (acc[m] < want) lo = m; else hi = m; }
    const k = (want - acc[lo]) / ((acc[hi] - acc[lo]) || 1);
    return [pts[lo][0] + (pts[hi][0] - pts[lo][0]) * k, pts[lo][1] + (pts[hi][1] - pts[lo][1]) * k];
  };
}
// the same curves as the lids of the eye, mirror images of each other about the eye's axis
const canH = walker([30, 686], [[L[0], L[1]], [520, 360, 1130, 360, Rc[0], Rc[1]], [PW - 30, 686]]);
const canL = walker([30, 714], [[L[0], L[1]], [520, 1040, 1130, 1040, Rc[0], Rc[1]], [PW - 30, 714]]);

// the red contact, and the moment the beam crosses it
const blipDeg = -40, blip = [cx + 178 * Math.cos(blipDeg * Math.PI / 180), cy + 178 * Math.sin(blipDeg * Math.PI / 180)];
const hit = ((360 + blipDeg) % 360) / 360 * LOOP;

function frame(t) {
  const theta = 360 * t / LOOP;
  let wedges = '';
  const r = R - 2, steps = 36, span = 70;
  for (let k = 0; k < steps; k++) {
    const a0 = (-span + (k * span) / steps) * Math.PI / 180, a1 = (-span + ((k + 1) * span) / steps) * Math.PI / 180;
    const op = (0.42 * ((k + 1) / steps) ** 1.6).toFixed(3);
    wedges += `<path d="M ${cx} ${cy} L ${cx + r * Math.cos(a0)} ${cy + r * Math.sin(a0)} A ${r} ${r} 0 0 1 ${cx + r * Math.cos(a1)} ${cy + r * Math.sin(a1)} Z" fill="#${HX.accent1}" fill-opacity="${op}"/>`;
  }
  // contact: lights up in 0.12 s, then fades over 3.8 s; the ping ring grows and fades in 1.2 s
  const d = ((t - hit) % LOOP + LOOP) % LOOP;
  const bo = d < 0.12 ? d / 0.12 : d < 0.2 ? 1 : d < 4 ? 1 - (d - 0.2) / 3.8 : 0;
  const ping = d < 1.2 ? `<circle cx="${blip[0]}" cy="${blip[1]}" r="${22 + 48 * d / 1.2}" fill="none" stroke="#${HX.accent3}" stroke-width="5" stroke-opacity="${(0.9 * (1 - d / 1.2)).toFixed(3)}"/>` : '';
  const pulse = (walk, f, core, glowId) => {
    const [x, y] = walk(f);
    const o = Math.min(1, f / 0.08, (1 - f) / 0.08).toFixed(3);
    return `<g opacity="${o}"><circle cx="${x}" cy="${y}" r="44" fill="url(#${glowId})"/><circle cx="${x}" cy="${y}" r="15" fill="#${core}"/></g>`;
  };
  const glowDef = (id, hex, a) => `<radialGradient id="${id}"><stop offset="0" stop-color="#${hex}" stop-opacity="${a}"/><stop offset="1" stop-color="#${hex}" stop-opacity="0"/></radialGradient>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${WIDTH}" height="${HEIGHT}" viewBox="0 0 ${PW} ${PH}"><defs>`
    + glowDef('gc', HX.accent1, 0.75) + glowDef('gb', HX.accent5, 0.75) + glowDef('gr', HX.accent3, 0.8) + '</defs>'
    + `<g transform="rotate(${theta.toFixed(3)} ${cx} ${cy})">${wedges}`
    + `<line x1="${cx}" y1="${cy}" x2="${cx + r}" y2="${cy}" stroke="#${HX.accent1}" stroke-opacity="0.3" stroke-width="16" stroke-linecap="round"/>`
    + `<line x1="${cx}" y1="${cy}" x2="${cx + r}" y2="${cy}" stroke="#${HX.accent1}" stroke-width="5" stroke-linecap="round"/></g>`
    + `<circle cx="${cx}" cy="${cy}" r="64" fill="#${HX.accent1}"/><circle cx="${cx}" cy="${cy}" r="28" fill="#${HX.dk1}"/>`
    + `<circle cx="${cx - 32}" cy="${cy - 36}" r="12" fill="#${HX.lt1}" fill-opacity="0.9"/>`
    + `<g opacity="${bo.toFixed(3)}"><circle cx="${blip[0]}" cy="${blip[1]}" r="52" fill="url(#gr)"/><circle cx="${blip[0]}" cy="${blip[1]}" r="18" fill="#${HX.accent3}"/></g>${ping}`
    + pulse(canH, (t / LOOP) % 1, HX.lt1, 'gc') + pulse(canL, (t / LOOP) % 1, HX.accent5, 'gb')
    + '</svg>';
}

async function main() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'eyegif-'));
  const base = await sharp(Buffer.from(sized(g.svg))).png().toBuffer();
  for (let i = 0; i < N; i++) {
    const buf = await sharp(base).composite([{ input: Buffer.from(frame(i / FPS)) }])
      .flatten({ background: '#' + HX.dk1 }).png().toBuffer();
    fs.writeFileSync(path.join(tmp, `f${String(i).padStart(3, '0')}.png`), buf);
  }
  // One palette for the whole loop (stable colours); the slide background must be in it exactly,
  // so the GIF has no visible edge on the slide.
  const pal = path.join(tmp, 'pal.png');
  const frames = path.join(tmp, 'f%03d.png');
  execFileSync(FFMPEG, ['-y', '-v', 'error', '-framerate', String(FPS), '-i', frames, '-vf', 'palettegen=stats_mode=full:reserve_transparent=0', pal]);
  const { data, info } = await sharp(pal).raw().toBuffer({ resolveWithObject: true });
  const bg = [0x0A, 0x14, 0x20];
  let best = 0, bestD = Infinity;
  for (let i = 0; i < info.width * info.height; i++) {
    const dd = bg.reduce((s, v, c) => s + (data[i * info.channels + c] - v) ** 2, 0);
    if (dd < bestD) { bestD = dd; best = i; }
  }
  bg.forEach((v, c) => { data[best * info.channels + c] = v; });
  await sharp(data, { raw: info }).png().toFile(pal + '.fixed.png');
  const out = path.join(__dirname, 'assets', 'eye.gif');
  execFileSync(FFMPEG, ['-y', '-v', 'error', '-framerate', String(FPS), '-i', frames, '-i', pal + '.fixed.png',
    '-lavfi', 'paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle', '-loop', '0', out]);
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log('wrote', out, `${WIDTH}x${HEIGHT}`, N, 'frames', (fs.statSync(out).size / 1e6).toFixed(1), 'MB');
}

main().catch((e) => { console.error(e); process.exit(1); });
