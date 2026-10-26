// Iconic visual for the title slide. Three variants: 'eye' (an eye watching the CAN bus, with a
// radar sweep in the iris), 'radar' and 'ev' (an electric car with its battery and CAN network).
// Each variant draws its static parts as one SVG (rendered by sharp, with a glow filter) and
// returns the native shapes that move, plus their animation spec for post.py. The moving eye is
// the exception: it is one looping GIF (eye_gif.js), so it needs no slide animation at all.

const path = require('path');

const glow = (id, sd) => `<filter id="${id}" filterUnits="userSpaceOnUse" x="-200" y="-200" width="4000" height="4000">`
  + `<feGaussianBlur stdDeviation="${sd}" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>`;

// a radar sweep: thin wedges whose opacity fades behind a bright leading edge (SVG has no conic gradient)
function sweepSvg(size, r, hex) {
  const c = size / 2;
  let wedges = '';
  const steps = 36, span = 70;
  for (let k = 0; k < steps; k++) {
    const a0 = (-span + (k * span) / steps) * Math.PI / 180, a1 = (-span + ((k + 1) * span) / steps) * Math.PI / 180;
    const op = (0.42 * ((k + 1) / steps) ** 1.6).toFixed(3);
    wedges += `<path d="M ${c} ${c} L ${c + r * Math.cos(a0)} ${c + r * Math.sin(a0)} A ${r} ${r} 0 0 1 ${c + r * Math.cos(a1)} ${c + r * Math.sin(a1)} Z" fill="#${hex}" fill-opacity="${op}"/>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 ${size} ${size}"><defs>${glow('g', 4)}</defs>`
    + wedges + `<line x1="${c}" y1="${c}" x2="${c + r}" y2="${c}" stroke="#${hex}" stroke-width="4" filter="url(#g)"/></svg>`;
}

// The static drawing of the CANvision eye (CAN lines, almond, iris, lids), in a 1650 x 1400 canvas.
// Shared by makeHero and by eye_gif.js, which renders the moving eye.
function eyeBase(HX) {
  const cyan = HX.accent1, blue = HX.accent5, ground = HX.dk1;
  const PW = 1650, PH = 1400, cx = 825, cy = 700, R = 245;
  const L = [285, 700], Rc = [1365, 700];
  const almond = `M ${L[0]} ${L[1]} C 520 360, 1130 360, ${Rc[0]} ${Rc[1]} C 1130 1040, 520 1040, ${L[0]} ${L[1]} Z`;
  let ticks = '';
  for (let i = 0; i < 90; i++) {
    const a = (i * 4) * Math.PI / 180, big = i % 5 === 0;
    const r1 = big ? 190 : 205, r2 = 226;
    ticks += `<line x1="${cx + r1 * Math.cos(a)}" y1="${cy + r1 * Math.sin(a)}" x2="${cx + r2 * Math.cos(a)}" y2="${cy + r2 * Math.sin(a)}" stroke="#${cyan}" stroke-opacity="${big ? 0.9 : 0.45}" stroke-width="${big ? 4 : 3}"/>`;
  }
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${PW}" height="${PH}" viewBox="0 0 ${PW} ${PH}"><defs>${glow('g', 9)}${glow('g2', 5)}
    <clipPath id="eye"><path d="${almond}"/></clipPath>
    <radialGradient id="ir" cx="${cx}" cy="${cy}" r="${R}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#${cyan}" stop-opacity="0.22"/><stop offset="1" stop-color="#${cyan}" stop-opacity="0.04"/></radialGradient>
    <linearGradient id="fadeL" x1="0" y1="0" x2="${L[0]}" y2="0" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity="1"/></linearGradient>
    <linearGradient id="fadeR" x1="${PW}" y1="0" x2="${Rc[0]}" y2="0" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity="1"/></linearGradient>
    <mask id="mL"><rect x="0" y="0" width="${PW / 2}" height="${PH}" fill="url(#fadeL)"/></mask>
    <mask id="mR"><rect x="${PW / 2}" y="0" width="${PW / 2}" height="${PH}" fill="url(#fadeR)"/></mask></defs>
    <g filter="url(#g2)" stroke-width="7" stroke-linecap="round">
      <g mask="url(#mL)"><line x1="0" y1="686" x2="${PW / 2}" y2="686" stroke="#${cyan}"/><line x1="0" y1="714" x2="${PW / 2}" y2="714" stroke="#${blue}"/></g>
      <g mask="url(#mR)"><line x1="${PW / 2}" y1="686" x2="${PW}" y2="686" stroke="#${cyan}"/><line x1="${PW / 2}" y1="714" x2="${PW}" y2="714" stroke="#${blue}"/></g></g>
    <path d="${almond}" fill="#${ground}"/>
    <path d="M 420 455 C 640 300, 1010 300, 1230 455" fill="none" stroke="#${cyan}" stroke-opacity="0.28" stroke-width="5" stroke-linecap="round"/>
    <path d="M 420 945 C 640 1100, 1010 1100, 1230 945" fill="none" stroke="#${cyan}" stroke-opacity="0.18" stroke-width="5" stroke-linecap="round"/>
    <g clip-path="url(#eye)">
      <circle cx="${cx}" cy="${cy}" r="${R}" fill="url(#ir)" stroke="#${cyan}" stroke-width="6"/>${ticks}
      <circle cx="${cx}" cy="${cy}" r="165" fill="none" stroke="#${cyan}" stroke-opacity="0.35" stroke-width="3" stroke-dasharray="16 11"/>
      <circle cx="${cx}" cy="${cy}" r="112" fill="none" stroke="#${cyan}" stroke-opacity="0.55" stroke-width="3"/></g>
    <path d="${almond}" fill="none" stroke="#${cyan}" stroke-width="9" filter="url(#g)"/></svg>`;
  return { PW, PH, cx, cy, R, L, Rc, svg };
}

async function makeHero(kind, k, opts = {}) {
  const { sharp, HX, C, S, IMG, ST, tint, hair, pres } = k;
  const png = async (svg) => 'image/png;base64,' + (await sharp(Buffer.from(svg)).png().toBuffer()).toString('base64');
  const cyan = HX.accent1, blue = HX.accent5, red = HX.accent3, ground = HX.dk1;
  const els = [], effects = [];
  const dot = (name, x, y, d, color, o = {}) => S(name, 'ellipse', { x: x - d / 2, y: y - d / 2, w: d, h: d, fill: { color, transparency: o.t || 0 }, line: o.line || { type: 'none' } });

  if (kind === 'eye') {
    // opts: cx, cy, w (placement, inches) and still (static emblem: no traffic, no contact, no motion)
    const { PW, PH, cx, cy, R, svg } = eyeBase(HX);
    const IW = opts.w || 5.75, ppi = PW / IW, IH = PH / ppi;
    const X0 = (opts.cx || 10.25) - IW / 2, Y0 = (opts.cy || 4.0) - IH / 2;
    if (!opts.still) {
      // The moving eye (radar sweep, red contact, CAN_H and CAN_L traffic) is one looping GIF
      // rendered by eye_gif.js on the same canvas. It plays by itself in PowerPoint and in WPS:
      // WPS ignored the custom slide animations this used to need (no contact, and clicks
      // before the traffic moved).
      els.push(IMG('!!h-eye', { path: path.join(__dirname, 'assets', 'eye.gif'), x: X0, y: Y0, w: IW, h: IH }));
      return { els, effects };
    }
    const px = (x) => X0 + x / ppi, py = (y) => Y0 + y / ppi, pd = (d) => d / ppi;
    els.push(IMG('!!h-base', { data: await png(svg), x: X0, y: Y0, w: IW, h: IH }));
    const SW = 2 * R + 10;
    els.push(IMG('!!h-sweep', { data: await png(sweepSvg(SW, R - 2, cyan)), x: px(cx - SW / 2), y: py(cy - SW / 2), w: pd(SW), h: pd(SW) }));
    els.push(dot('!!h-pupil', px(cx), py(cy), pd(128), C.accent1));
    els.push(dot('!!h-hole', px(cx), py(cy), pd(56), C.background1));
    els.push(dot('!!h-glint', px(cx - 32), py(cy - 36), pd(24), C.text1, { t: 10 }));
    return { els, effects };
  }

  if (kind === 'radar') {
    const P = 1400, IW = 4.9, ppi = P / IW, X0 = 10.25 - IW / 2, Y0 = 4.0 - IW / 2, c = P / 2;
    let ticks = '';
    for (let i = 0; i < 120; i++) {
      const a = i * 3 * Math.PI / 180, big = i % 10 === 0;
      ticks += `<line x1="${c + (big ? 628 : 645) * Math.cos(a)}" y1="${c + (big ? 628 : 645) * Math.sin(a)}" x2="${c + 668 * Math.cos(a)}" y2="${c + 668 * Math.sin(a)}" stroke="#${cyan}" stroke-opacity="${big ? 0.9 : 0.4}" stroke-width="3"/>`;
    }
    const blips = [[0.32, 200], [0.55, 120], [0.7, 300], [0.45, 250], [0.25, 40], [0.62, 330], [0.4, 160]];
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${P}" height="${P}" viewBox="0 0 ${P} ${P}"><defs>${glow('g', 8)}
      <radialGradient id="bg" cx="${c}" cy="${c}" r="620" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#${cyan}" stop-opacity="0.12"/><stop offset="1" stop-color="#${cyan}" stop-opacity="0.02"/></radialGradient></defs>
      <circle cx="${c}" cy="${c}" r="620" fill="url(#bg)" stroke="#${cyan}" stroke-width="6" filter="url(#g)"/>${ticks}
      ${[460, 300, 150].map((r, i) => `<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="#${cyan}" stroke-opacity="${0.4 - i * 0.06}" stroke-width="3"${i === 1 ? ' stroke-dasharray="16 11"' : ''}/>`).join('')}
      <line x1="${c - 620}" y1="${c}" x2="${c + 620}" y2="${c}" stroke="#${cyan}" stroke-opacity="0.18" stroke-width="3"/>
      <line x1="${c}" y1="${c - 620}" x2="${c}" y2="${c + 620}" stroke="#${cyan}" stroke-opacity="0.18" stroke-width="3"/>
      ${blips.map(([f, deg]) => `<circle cx="${c + 620 * f * Math.cos(deg * Math.PI / 180)}" cy="${c + 620 * f * Math.sin(deg * Math.PI / 180)}" r="11" fill="#${HX.lt2}" fill-opacity="0.75"/>`).join('')}
      <circle cx="${c}" cy="${c}" r="16" fill="#${cyan}" filter="url(#g)"/></svg>`;
    const px = (x) => X0 + x / ppi, py = (y) => Y0 + y / ppi, pd = (d) => d / ppi;
    els.push(IMG('!!h-base', { data: await png(svg), x: X0, y: Y0, w: IW, h: IW }));
    const SW = 1250;
    els.push(IMG('!!h-sweep', { data: await png(sweepSvg(SW, 618, cyan)), x: px(c - SW / 2), y: py(c - SW / 2), w: pd(SW), h: pd(SW) }));
    const a = -35 * Math.PI / 180;
    els.push(dot('!!h-blipring', px(c + 400 * Math.cos(a)), py(c + 400 * Math.sin(a)), pd(70), C.accent3, { t: 100, line: { color: C.accent3, width: 1.5 } }));
    els.push(dot('!!h-blip', px(c + 400 * Math.cos(a)), py(c + 400 * Math.sin(a)), pd(30), C.accent3));
    effects.push({ type: 'fade', name: '!!h-base', dur: 700, delay: 0 });
    effects.push({ type: 'spin', name: '!!h-sweep', dur: 4000, repeat: true, delay: 0 });
    effects.push({ type: 'pulse', name: '!!h-blipring', scale: 1.6, dur: 600, repeat: true, delay: 300 });
    return { els, effects };
  }

  if (kind === 'ev') {
    const PW = 2000, PH = 1000, IW = 5.35, ppi = PW / IW, IH = PH / ppi;
    const X0 = 10.25 - IW / 2, Y0 = 4.05 - IH / 2;
    const body = 'M 150 640 C 112 640, 100 600, 104 560 L 112 505 C 118 470, 150 448, 205 438 '
      + 'C 340 412, 520 265, 770 222 C 990 186, 1200 190, 1335 246 C 1455 296, 1555 352, 1700 378 '
      + 'C 1820 400, 1905 428, 1918 488 C 1928 540, 1922 600, 1885 640 L 1670 640 A 175 175 0 0 0 1320 640 '
      + 'L 650 640 A 175 175 0 0 0 300 640 Z';
    const glass = 'M 360 445 C 520 330, 690 268, 860 258 L 1250 262 C 1320 268, 1385 300, 1450 360 L 1440 372 L 360 455 Z';
    const wheel = (x) => `<circle cx="${x}" cy="640" r="140" fill="#${ground}" stroke="#${cyan}" stroke-width="8"/><circle cx="${x}" cy="640" r="62" fill="none" stroke="#${cyan}" stroke-opacity="0.55" stroke-width="5"/>`;
    let cells = '';
    for (let i = 0; i < 12; i++) cells += `<rect x="${672 + i * 54}" y="560" width="44" height="46" rx="6" fill="#${cyan}" fill-opacity="0.55"/>`;
    const nodes = [[360, 520], [760, 480], [1140, 480], [1560, 470], [1790, 520]];
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${PW}" height="${PH}" viewBox="0 0 ${PW} ${PH}"><defs>${glow('g', 9)}${glow('g2', 5)}
      <linearGradient id="bf" x1="0" y1="200" x2="0" y2="660" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#${cyan}" stop-opacity="0.10"/><stop offset="1" stop-color="#${cyan}" stop-opacity="0.02"/></linearGradient></defs>
      <ellipse cx="1000" cy="800" rx="900" ry="40" fill="#${cyan}" fill-opacity="0.06"/>
      <path d="${body}" fill="url(#bf)" stroke="#${cyan}" stroke-width="9" stroke-linejoin="round" filter="url(#g)"/>
      <path d="${glass}" fill="#${cyan}" fill-opacity="0.07" stroke="#${cyan}" stroke-opacity="0.45" stroke-width="5" stroke-linejoin="round"/>
      <rect x="655" y="545" width="680" height="76" rx="14" fill="none" stroke="#${cyan}" stroke-width="6" filter="url(#g2)"/>${cells}
      <line x1="360" y1="520" x2="1790" y2="520" stroke="#${blue}" stroke-opacity="0.9" stroke-width="5" filter="url(#g2)"/>
      ${nodes.map(([x, y]) => `<line x1="${x}" y1="${y}" x2="${x}" y2="520" stroke="#${blue}" stroke-width="4"/><circle cx="${x}" cy="${y}" r="18" fill="#${ground}" stroke="#${blue}" stroke-width="6"/>`).join('')}
      ${wheel(475)}${wheel(1495)}</svg>`;
    const px = (x) => X0 + x / ppi, py = (y) => Y0 + y / ppi, pd = (d) => d / ppi;
    els.push(IMG('!!h-base', { data: await png(svg), x: X0, y: Y0, w: IW, h: IH }));
    els.push(dot('!!h-fl', px(380), py(520), 0.11, C.accent1), dot('!!h-fr', px(1770), py(520), 0.11, C.accent1));
    els.push(dot('!!h-blip', px(1560), py(470), pd(40), C.accent3, { t: 100, line: { color: C.accent3, width: 1.5 } }));
    effects.push({ type: 'fade', name: '!!h-base', dur: 700, delay: 0 });
    effects.push({ type: 'motion', name: '!!h-fl', dx: pd(1390), dy: 0, dur: 2400, repeat: true, delay: 0 });
    effects.push({ type: 'motion', name: '!!h-fr', dx: -pd(1390), dy: 0, dur: 2400, repeat: true, delay: 1200 });
    effects.push({ type: 'pulse', name: '!!h-blip', scale: 1.7, dur: 600, repeat: true, delay: 300 });
    return { els, effects };
  }
  throw new Error('unknown hero ' + kind);
}

module.exports = { makeHero, eyeBase };
