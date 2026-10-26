// CANvisionNative jury defense deck: question -> morph -> content storytelling.
// node build.js [out.pptx]   then: python post.py out.pptx  (morph transitions + dark colour map)
const fs = require('fs');
const path = require('path');
const pptxgen = require('pptxgenjs');
const React = require('react');
const RDS = require('react-dom/server');
const sharp = require('sharp');
const lu = require('react-icons/lu');
const { applyTheme } = require('./apply_theme.js');
const { makeHero } = require('./hero.js');

const A = (f) => path.join(__dirname, 'assets', f);
const OUT = process.argv[2] || path.join(__dirname, '..', 'CANvisionNative_defense.pptx');

// Dark colour map (bg1=dk1, tx1=lt1, bg2=dk2, tx2=lt2) is set by post.py,
// so scheme bg1 = navy ground, tx1 = white, bg2 = card navy, tx2 = muted text.
const THEME = {
  name: 'CANvision Dark',
  headFontFace: 'Segoe UI Semibold',
  bodyFontFace: 'Segoe UI',
  colors: {
    dk1: '0A1420', lt1: 'FFFFFF', dk2: '14263B', lt2: '9AAEC2',
    accent1: '2FF0D6', accent2: 'FFB245', accent3: 'FF5A68', accent4: '35E6A1', accent5: '6EA8FE', accent6: 'B48CFF',
    hlink: '2FF0D6', folHlink: 'B48CFF',
  },
};
const HX = THEME.colors;
const MONO = 'Consolas';
const HEAD = '+mj-lt';
const W = 13.333;

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE';
pres.author = 'Mohamed Mootaz Ben Kraiem';
pres.title = 'CANvisionNative';
pres.subject = 'Graduation project defense, ESPRIT 2025/2026';
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const SCHEME_HEX = { tx1: HX.lt1, tx2: HX.lt2, bg1: HX.dk1, bg2: HX.dk2 };
const hexOf = (c) => SCHEME_HEX[c] || HX[c] || c;

// ---------- icons and images ----------
const iconCache = new Map();
async function icon(name, color, px = 256) {
  const hex = hexOf(color);
  const key = name + hex;
  if (iconCache.has(key)) return iconCache.get(key);
  const Comp = lu[name];
  if (!Comp) throw new Error('missing icon ' + name);
  let svg = RDS.renderToStaticMarkup(React.createElement(Comp, { size: px, color: '#' + hex }));
  svg = svg.replace(/currentColor/g, '#' + hex);
  const buf = await sharp(Buffer.from(svg)).resize(px, px).png().toBuffer();
  const d = 'image/png;base64,' + buf.toString('base64');
  iconCache.set(key, d);
  return d;
}
const dims = {};
async function loadDims() {
  for (const f of fs.readdirSync(path.join(__dirname, 'assets'))) {
    if (!f.endsWith('.png')) continue;
    const m = await sharp(A(f)).metadata();
    dims[f] = [m.width, m.height];
  }
}
function fit(f, x, y, w, h, align = 'center', valign = 'middle') {
  const [iw, ih] = dims[f];
  const r = Math.min(w / iw, h / ih);
  const fw = iw * r, fh = ih * r;
  let fx = x + (w - fw) / 2, fy = y + (h - fh) / 2;
  if (align === 'left') fx = x;
  if (align === 'right') fx = x + w - fw;
  if (valign === 'top') fy = y;
  return { x: fx, y: fy, w: fw, h: fh };
}

// ---------- element descriptors ----------
const T = (name, text, o) => ({ k: 'text', name, text, o });            // text box
const ST = (name, text, o) => ({ k: 'stext', name, text, o });          // shape with text
const S = (name, shape, o) => ({ k: 'shape', name, shape, o });
const IMG = (name, o) => ({ k: 'img', name, o });
const CH = (name, type, data, o) => ({ k: 'chart', name, type, data, o });
const SHAPES = () => ({ rect: pres.shapes.RECTANGLE, roundRect: pres.shapes.ROUNDED_RECTANGLE, ellipse: pres.shapes.OVAL, line: pres.shapes.LINE, diamond: pres.shapes.DIAMOND });
const tint = (color, t = 86) => ({ color, transparency: t });
const hair = (color = C.text1, t = 86, width = 0.75) => ({ color, width, transparency: t });

function card(name, x, y, w, h, o = {}) {
  return S(name, 'roundRect', { x, y, w, h, rectRadius: o.r ?? 0.1, fill: o.fill ?? { color: C.background2 }, line: o.line ?? hair() });
}
async function iconTile(name, x, y, s, iconName, color, o = {}) {
  const p = s * 0.21;
  return [
    S(name + '-bg', 'roundRect', { x, y, w: s, h: s, rectRadius: s * 0.22, fill: o.fill ?? tint(color, 84), line: o.line ?? hair(color, 55) }),
    IMG(name + '-ic', { data: await icon(iconName, o.iconColor ?? color), x: x + p, y: y + p, w: s - 2 * p, h: s - 2 * p }),
  ];
}
async function iconOnly(name, x, y, s, iconName, color) {
  return IMG(name, { data: await icon(iconName, color), x, y, w: s, h: s });
}
function logoTile(name, x, y, w, h, files, o = {}) {
  const pad = o.pad ?? 0.12;
  const els = [S(name + '-bg', 'roundRect', { x, y, w, h, rectRadius: o.r ?? 0.08, fill: { color: C.text1 }, line: { type: 'none' } })];
  const n = files.length, gap = 0.18;
  const cw = (w - 2 * pad - gap * (n - 1)) / n;
  files.forEach((f, i) => els.push(IMG(`${name}-l${i}`, { path: A(f), ...fit(f, x + pad + i * (cw + gap), y + pad, cw, h - 2 * pad) })));
  return els;
}
function arrow(name, x, y, w, h, o = {}) {
  return S(name, 'line', { x, y, w, h, flipV: o.flipV, flipH: o.flipH, line: { color: o.color ?? C.text2, width: o.width ?? 1.5, endArrowType: o.noHead ? undefined : 'triangle', beginArrowType: o.both ? 'triangle' : undefined, dashType: o.dash, transparency: o.t } });
}
// text helpers
const para = (text, o = {}) => ({ text, options: { breakLine: true, ...o } });
const lastPara = (text, o = {}) => ({ text, options: { ...o } });

// ---------- deck frame: sections, tags, questions, progress ----------
const SECS = [
  { id: '100', label: 'CONTEXT' }, { id: '200', label: 'PROBLEM' }, { id: '300', label: 'OBJECTIVES AND REQUIREMENTS' }, { id: '400', label: 'SOLUTION' },
  { id: '500', label: 'DEMO' }, { id: '600', label: 'VALIDATION' }, { id: '700', label: 'LIMITS' }, { id: '800', label: 'CONCLUSION' },
];
const tagText = (si) => `0x${SECS[si].id}  ·  ${SECS[si].label}`;
function tagEl(si, mode) {
  const c = mode === 'c';
  return T(`!!tag-${si}`, tagText(si), { x: c ? 1.17 : 0.6, y: c ? 2.3 : 0.4, w: c ? 11 : 8, h: c ? 0.35 : 0.28, fontFace: MONO, fontSize: c ? 15 : 12, color: C.accent1, align: c ? 'center' : 'left', charSpacing: 2, bold: true });
}
function qEl(qid, text, mode) {
  const c = mode === 'c';
  return T(`!!q-${qid}`, text, { x: c ? 1.17 : 0.6, y: c ? 2.8 : 0.68, w: c ? 11 : 12.1, h: c ? 1.75 : 0.6, fontFace: HEAD, fontSize: c ? 42 : 26, color: C.text1, align: c ? 'center' : 'left', valign: c ? 'top' : 'top', lineSpacingMultiple: 0.95 });
}
function progress(si, mode) {
  const els = [];
  const big = mode === 'q';
  const cw = big ? 0.56 : 0.2, ch = big ? 0.32 : 0.09, gap = big ? 0.1 : 0.05;
  const n = SECS.length;  // 8 sections, like the 8 data bytes of a CAN frame
  const total = n * cw + (n - 1) * gap;
  const x0 = big ? (W - total) / 2 : 0.6, y = big ? 5.0 : 7.12;
  for (let i = 0; i < n; i++) {
    const cur = i === si, done = i < si;
    const o = {
      shape: pres.shapes.ROUNDED_RECTANGLE, x: x0 + i * (cw + gap), y, w: cw, h: ch, rectRadius: big ? 0.06 : 0.02,
      fill: cur ? { color: C.accent1 } : done ? tint(C.accent1, 72) : tint(C.text1, 94),
      line: cur || done ? hair(C.accent1, cur ? 0 : 45) : hair(C.text2, 55),
      fontFace: MONO, fontSize: 11, bold: cur, color: cur ? C.background1 : C.text2, align: 'center', valign: 'middle', margin: 0,
    };
    els.push(ST(`!!prog-${i}`, big ? `0${i + 1}` : '', { ...o, _link: i }));  // jump to section i (set at render)
  }
  return els;
}
const fades = (names, delay, dur = 400) => names.map((n) => ({ type: 'fade', name: n, dur, delay }));
const head = (si, qid, q) => [tagEl(si, 'h'), qEl(qid, q, 'h'), ...progress(si, 'c')];
const sub = (text, color = C.accent1) => T('!!sub', text, { x: 0.6, y: 1.24, w: 12.1, h: 0.38, fontSize: 16, color, bold: true });
const zoomBox = () => card('!!zoom', 0.6, 1.78, 12.13, 4.97, { fill: { color: C.background2 }, line: hair(C.accent1, 62, 1), r: 0.08 });

// ---------- slides ----------
const slides = [];
const add = (sec, els, notes, o = {}) => slides.push({ sec, els, notes, isQ: !!o.isQ, layout: o.layout || 'CV_DARK', anim: o.anim || null });
const Q = (si, qid, q, notes) => add(SECS[si].label, [tagEl(si, 'c'), qEl(qid, q, 'c'), ...progress(si, 'q')], notes, { isQ: true });

async function build() {
  await loadDims();

  // 1. Title: a clean welcome page (title, subtitle, presenter, supervisors) and one iconic
  // visual on the right, drawn by hero.js. HERO=eye|radar|ev picks the visual.
  {
    const esp = fit('esprit_white.png', 8.95, 0.48, 1.7, 0.62, 'right');
    const cap = fit('capgemini_white.png', 10.92, 0.6, 1.81, 0.4, 'right');
    const hero = await makeHero(process.env.HERO || 'eye', { sharp, HX, C, S, IMG, ST, tint, hair, pres });
    const sup = (i, x, label, name, org) => [
      T(`!!sup${i}-l`, label, { x, y: 5.4, w: 3.3, h: 0.25, fontFace: MONO, fontSize: 10, bold: true, color: C.text2, charSpacing: 1 }),
      T(`!!sup${i}-n`, name, { x, y: 5.65, w: 3.3, h: 0.36, fontFace: HEAD, fontSize: 16, color: C.text1 }),
      T(`!!sup${i}-o`, org, { x, y: 6.0, w: 3.3, h: 0.28, fontSize: 12, color: C.text2 }),
    ];
    add('Opening', [
      ...hero.els,
      T('!!kicker', 'GRADUATION PROJECT  ·  INFORMATION TECHNOLOGY  ·  2025/2026', { x: 0.7, y: 0.66, w: 7.2, h: 0.3, fontFace: MONO, fontSize: 12, color: C.accent1, bold: true, charSpacing: 1 }),
      T('!!title', [{ text: 'CANvision', options: { color: C.text1 } }, { text: 'Native', options: { color: C.accent1 } }], { x: 0.7, y: 1.7, w: 7.2, h: 1.05, fontFace: HEAD, fontSize: 58 }),
      T('!!subtitle', [
        { text: 'A diagnostic and validation platform for the', options: { color: C.text2, breakLine: true } }, { text: 'CAN traffic', options: { color: C.text1 } },
        { text: ' of ', options: { color: C.text2 } }, { text: 'Battery Management Systems', options: { color: C.text1 } },
      ], { x: 0.7, y: 2.85, w: 7.0, h: 0.95, fontSize: 21 }),
      T('!!author-l', 'PRESENTED BY', { x: 0.7, y: 4.3, w: 3.3, h: 0.25, fontFace: MONO, fontSize: 10, bold: true, color: C.accent1, charSpacing: 1 }),
      T('!!author', 'Mohamed Mootaz Ben Kraiem', { x: 0.7, y: 4.55, w: 7.0, h: 0.45, fontFace: HEAD, fontSize: 22, color: C.text1 }),
      ...sup(0, 0.7, 'ACADEMIC SUPERVISOR', 'Mrs Nadia Boulifa', 'ESPRIT'),
      ...sup(1, 4.1, 'CORPORATE SUPERVISOR', 'Mr Hamda Guizani', 'Capgemini Engineering'),
      IMG('!!logo-esprit', { path: A('esprit_white.png'), ...esp }),
      S('!!logo-sep', 'line', { x: 10.77, y: 0.55, w: 0, h: 0.5, line: hair(C.text2, 40, 1) }),
      IMG('!!logo-capg', { path: A('capgemini_white.png'), ...cap }),
    ], 'Hello everyone, and welcome. Thank you for being here. My name is Mohamed Mootaz Ben Kraiem, and I am going to present my graduation project, CANvisionNative: a diagnostic and validation platform for the CAN traffic of Battery Management Systems. I carried it out at Capgemini Engineering, where I follow a work and study program as a QA tester of BMS software for BMW Group, under the supervision of Mrs Nadia Boulifa at ESPRIT and Mr Hamda Guizani at Capgemini Engineering.', {
      layout: 'CV_PLAIN',
      // the eye moves by itself (a looping GIF); the other heroes use slide animations
      anim: hero.effects.length ? [{ trigger: 'auto', effects: hero.effects }] : null,
    });
  }

  // Roadmap. ROAD=summary|acts|steps|eye|numerals|time picks the design. Static: no animation on this slide.
  {
    const ROAD = process.env.ROAD || 'simple2';
    const els = [T('!!rm-tag', '0x000  ·  ROADMAP', { x: 0.6, y: 0.4, w: 8, h: 0.28, fontFace: MONO, fontSize: 12, color: C.accent1, bold: true, charSpacing: 2 })];
    const colOf = (i) => (i === 4 ? C.accent2 : C.accent1);
    if (ROAD === 'steps') {
      // eight bars rising like a staircase, from the context to the conclusion
      els.push(T('!!rm-title', 'Roadmap', { x: 0.6, y: 0.68, w: 12.1, h: 0.6, fontFace: HEAD, fontSize: 26, color: C.text1 }));
      const bw = 1.3, gap = 0.2, x0 = (W - (8 * bw + 7 * gap)) / 2, base = 6.55;
      for (let i = 0; i < 8; i++) {
        const x = x0 + i * (bw + gap), h = 1.0 + i * 0.47, y = base - h, col = colOf(i);
        els.push(ST(`!!rm${i}`, `0${i + 1}`, { shape: pres.shapes.ROUNDED_RECTANGLE, x, y, w: bw, h, rectRadius: 0.06, fill: tint(col, i === 4 ? 70 : 80 - i * 2), line: hair(col, 20, 1.25), fontFace: MONO, fontSize: 18, bold: true, color: col, align: 'center', valign: 'top', margin: [10, 0, 0, 0], _link: i }));
        els.push(T(`!!rm${i}-t`, SECS[i].label, { x: x - 0.15, y: y - 0.42, w: bw + 0.3, h: 0.32, fontFace: MONO, fontSize: 12, bold: true, color: i === 4 ? C.accent2 : C.text1, align: 'center', _link: i }));
      }
      els.push(S('!!rm-base', 'line', { x: x0 - 0.2, y: base, w: 8 * bw + 7 * gap + 0.4, h: 0, line: hair(C.text1, 75, 1) }));
    } else if (ROAD === 'eye') {
      // the CANvision eye on the left, the eight chapters set large on the right
      const hero = await makeHero('eye', { sharp, HX, C, S, IMG, ST, tint, hair, pres }, { cx: 3.3, cy: 4.0, w: 5.6, still: true });
      els.push(...hero.els);
      for (let i = 0; i < 8; i++) {
        const y = 0.95 + i * 0.72, demo = i === 4;
        els.push(T(`!!rm${i}-t`, [{ text: `0${i + 1}   `, options: { fontFace: MONO, fontSize: 14, bold: true, color: colOf(i) } }, { text: SECS[i].label[0] + SECS[i].label.slice(1).toLowerCase(), options: { fontFace: HEAD, fontSize: 26, color: demo ? C.accent2 : C.text1 } }, ...(demo ? [{ text: '   5 min', options: { fontFace: MONO, fontSize: 12, color: C.accent2 } }] : [])],
          { x: 7.0, y, w: 5.7, h: 0.62, valign: 'middle', _link: i }));
      }
    } else if (ROAD === 'numerals') {
      // a bold band of large numerals, one per chapter
      els.push(T('!!rm-title', 'Roadmap', { x: 0.6, y: 0.68, w: 12.1, h: 0.6, fontFace: HEAD, fontSize: 26, color: C.text1 }));
      const cw = 1.5, x0 = (W - 8 * cw) / 2;
      els.push(S('!!rm-rule', 'line', { x: x0 + 0.1, y: 4.2, w: 8 * cw - 0.2, h: 0, line: hair(C.text1, 80, 1) }));
      for (let i = 0; i < 8; i++) {
        const x = x0 + i * cw;
        els.push(T(`!!rm${i}-n`, `0${i + 1}`, { x, y: 2.6, w: cw, h: 1.45, fontFace: HEAD, fontSize: 66, color: colOf(i), align: 'center', valign: 'bottom', _link: i }));
        els.push(T(`!!rm${i}-t`, SECS[i].label, { x: x - 0.1, y: 4.4, w: cw + 0.2, h: 0.32, fontFace: MONO, fontSize: 12, bold: true, color: i === 4 ? C.accent2 : C.text1, align: 'center', _link: i }));
        if (i === 4) els.push(T('!!rm-demo-m', '5 min', { x, y: 4.75, w: cw, h: 0.3, fontFace: MONO, fontSize: 11, color: C.accent2, align: 'center' }));
      }
    } else if (ROAD === 'simple2') {
      // Plain summary with a little more substance: number, name and one line per part, thin rules.
      els.length = 0;
      els.push(T('!!rm-tag', 'Summary', { x: 0.6, y: 0.62, w: 12.1, h: 0.75, fontFace: HEAD, fontSize: 32, color: C.text1 }));
      const ITEMS = [
        ['Context', 'The host company and how a CAN bus works'], ['Problem', 'What is missing today and the existing tools'],
        ['Objectives and requirements', 'The objectives, the method and the requirements'], ['Proposed solution', 'Architecture, detection, models and explanation'],
        ['Demonstration', 'The real application on real recordings'], ['Validation', 'Two iterations on real recordings'],
        ['Limits', 'What is not proven yet'], ['Conclusion', 'Results and next steps'],
      ];
      ITEMS.forEach(([n, d], i) => {
        const x = i < 4 ? 0.9 : 7.05, y = 1.9 + (i % 4) * 1.22;
        els.push(T(`!!sp${i}-n`, `0${i + 1}`, { x, y: y - 0.04, w: 0.85, h: 0.5, fontFace: HEAD, fontSize: 24, color: C.accent1 }));
        els.push(T(`!!sp${i}`, [{ text: n, options: { fontSize: 21, color: C.text1, breakLine: true } }, { text: d, options: { fontSize: 13.5, color: C.text2 } }], { x: x + 0.9, y, w: 4.75, h: 0.9, valign: 'top', _link: i }));
        if (i % 4 < 3) els.push(S(`!!sp${i}-rule`, 'line', { x, y: y + 1.04, w: 5.65, h: 0, line: hair(C.text1, 88, 0.75) }));
      });
    } else if (ROAD === 'simple') {
      // Plain summary: a title and a numbered list in two columns. Nothing else.
      els.length = 0;
      els.push(T('!!rm-tag', 'Summary', { x: 0.6, y: 0.62, w: 12.1, h: 0.75, fontFace: HEAD, fontSize: 32, color: C.text1 }));
      const NAMES = ['Context', 'Problem', 'Objectives and requirements', 'Proposed solution', 'Demonstration', 'Validation', 'Limits', 'Conclusion'];
      NAMES.forEach((n, i) => {
        const x = i < 4 ? 0.9 : 7.0, y = 2.0 + (i % 4) * 1.05;
        els.push(T(`!!sp${i}`, [{ text: `${i + 1}.  `, options: { color: C.accent1 } }, { text: n, options: { color: C.text1 } }], { x, y, w: 5.6, h: 0.6, fontSize: 24, valign: 'middle', _link: i }));
      });
    } else if (ROAD === 'summary') {
      // Summary, after the student's reference: header strip, big title on the left, numbered rows
      // on a thread on the right, each with an icon, a title, a subtitle and its slide number.
      // {{sec:i}} is replaced at render time by the first slide of section i.
      els.length = 0;
      els.push(T('!!rm-tag', [{ text: 'CANvision', options: { color: C.text1 } }, { text: 'Native', options: { color: C.accent1 } }], { x: 0.6, y: 0.32, w: 2.6, h: 0.45, fontFace: HEAD, fontSize: 20, valign: 'middle' }));
      els.push(S('!!sm-sep', 'line', { x: 3.25, y: 0.38, w: 0, h: 0.34, line: hair(C.accent1, 30, 1.25) }));
      els.push(T('!!sm-proj', 'GRADUATION PROJECT  ·  2025/2026', { x: 3.45, y: 0.32, w: 4.5, h: 0.45, fontFace: MONO, fontSize: 11, color: C.text2, valign: 'middle', charSpacing: 2 }));
      els.push(T('!!sm-org', 'ESPRIT  |  CAPGEMINI ENGINEERING', { x: 7.73, y: 0.32, w: 5.0, h: 0.45, fontFace: MONO, fontSize: 11, color: C.text2, align: 'right', valign: 'middle', charSpacing: 2 }));
      els.push(S('!!sm-rule', 'line', { x: 0.6, y: 0.9, w: 12.13, h: 0, line: hair(C.text1, 82, 0.75) }));
      els.push(S('!!sm-rule-a', 'line', { x: 0.6, y: 0.9, w: 0.75, h: 0, line: { color: C.accent1, width: 2 } }));
      // faint arcs in the lower left corner
      [[3.6, 16], [4.6, 10]].forEach(([r, wd], k) => els.push(S(`!!sm-arc${k}`, 'ellipse', { x: 0.2 - r, y: 7.9 - r, w: 2 * r, h: 2 * r, fill: { color: C.background1, transparency: 100 }, line: { color: C.text1, width: wd, transparency: 95 } })));
      els.push(T('!!sm-title', 'Summary', { x: 0.6, y: 2.45, w: 4.6, h: 1.25, fontFace: HEAD, fontSize: 66, bold: true, color: C.text1 }));
      els.push(S('!!sm-acc', 'rect', { x: 0.65, y: 3.78, w: 0.6, h: 0.06, fill: { color: C.accent1 }, line: { type: 'none' } }));
      els.push(T('!!sm-sub', 'PRESENTATION OUTLINE', { x: 0.65, y: 4.02, w: 4.6, h: 0.35, fontFace: MONO, fontSize: 13, color: C.text2, charSpacing: 8 }));
      els.push(T('!!sm-foot', 'BATTERY MANAGEMENT SYSTEMS  |  CAN TRAFFIC ANALYSIS', { x: 0.6, y: 6.95, w: 4.5, h: 0.3, fontFace: MONO, fontSize: 9.5, color: C.text2, charSpacing: 0.5 }));
      const ROWS = [
        ['LuFileText', 'Context', 'The host company, and how a CAN bus works'],
        ['LuTriangleAlert', 'Problem', 'What is missing today, and the existing tools'],
        ['LuListChecks', 'Objectives and requirements', 'The objectives, the method and the requirements'],
        ['LuSettings', 'Proposed solution', 'Architecture, detection, models per vehicle, explanation'],
        ['LuMonitorPlay', 'Demonstration', 'The real application, 5 minutes'],
        ['LuBadgeCheck', 'Validation', 'Two iterations, on recordings never seen'],
        ['LuCircleAlert', 'Limits', 'What is not proven yet'],
        ['LuFlag', 'Conclusion', 'Results and next steps'],
      ];
      const tx = 5.2, ts = 0.6, rx = 6.35, rw = 12.73 - 6.35, rh = 0.62, gap = 0.1, y0 = 1.25;
      els.push(S('!!sm-thread', 'line', { x: tx + ts / 2, y: y0 + rh / 2, w: 0, h: 7 * (rh + gap), line: hair(C.text2, 55, 1.25) }));
      for (let i = 0; i < 8; i++) {
        const y = y0 + i * (rh + gap), hl = i === 4, col = hl ? C.accent2 : C.accent1, cy = y + rh / 2;
        els.push(ST(`!!sm${i}-n`, `0${i + 1}`, { shape: pres.shapes.ROUNDED_RECTANGLE, x: tx, y: y + (rh - ts) / 2, w: ts, h: ts, rectRadius: 0.1, fill: hl ? { color: C.accent2 } : { color: C.background2 }, line: hair(hl ? C.accent2 : C.text1, hl ? 0 : 80, 1), fontFace: HEAD, fontSize: 17, bold: true, color: hl ? C.background1 : C.text1, align: 'center', valign: 'middle', margin: 0, _link: i }));
        els.push(S(`!!sm${i}-ln`, 'line', { x: tx + ts, y: cy, w: rx - tx - ts, h: 0, line: hair(hl ? C.accent2 : C.text2, hl ? 20 : 55, 1.25) }));
        els.push(S(`!!sm${i}-dot`, 'ellipse', { x: tx + ts + 0.2, y: cy - 0.06, w: 0.12, h: 0.12, fill: { color: hl ? C.accent2 : C.text2 }, line: { type: 'none' } }));
        const cd = card(`!!sm${i}`, rx, y, rw, rh, { fill: hl ? tint(C.accent2, 86) : { color: C.background2 }, line: hair(hl ? C.accent2 : C.text1, hl ? 35 : 82, 1), r: 0.08 });
        cd.o._link = i;
        els.push(cd);
        els.push(IMG(`!!sm${i}-i`, { data: await icon(ROWS[i][0], hl ? C.accent2 : C.accent1), x: rx + 0.3, y: cy - 0.17, w: 0.34, h: 0.34 }));
        els.push(S(`!!sm${i}-d1`, 'line', { x: rx + 0.95, y: y + 0.13, w: 0, h: rh - 0.26, line: hair(hl ? C.accent2 : C.text1, hl ? 40 : 80, 1) }));
        els.push(T(`!!sm${i}-t`, [{ text: ROWS[i][1], options: { fontFace: HEAD, fontSize: 15, bold: true, color: hl ? C.accent2 : C.text1, breakLine: true } }, { text: ROWS[i][2], options: { fontSize: 11.5, color: C.text2 } }], { x: rx + 1.15, y: y + 0.02, w: rw - 2.4, h: rh - 0.04, valign: 'middle' }));
        els.push(S(`!!sm${i}-d2`, 'line', { x: rx + rw - 1.05, y: y + 0.13, w: 0, h: rh - 0.26, line: hair(hl ? C.accent2 : C.text1, hl ? 40 : 80, 1) }));
        els.push(T(`!!sm${i}-p`, `p. {{sec:${i}}}`, { x: rx + rw - 0.95, y, w: 0.8, h: rh, fontSize: 12.5, color: hl ? C.accent2 : C.text2, align: 'center', valign: 'middle' }));
      }
    } else if (ROAD === 'acts') {
      // The story in three acts. Each act has its driving question; under it, the exact questions
      // the jury will meet on the section slides, so the roadmap and the talk tell the same story.
      els.push(T('!!rm-title', 'The story in three acts', { x: 0.6, y: 0.68, w: 12.1, h: 0.6, fontFace: HEAD, fontSize: 26, color: C.text1 }));
      const ACTS = [
        ['ACT I', 'Why', 'Why does a BMS engineer need it?', [[0, 'How do the computers of a car talk to each other?'], [1, 'What are the problems?'], [2, 'What must the platform do?']]],
        ['ACT II', 'How', 'How does CANvisionNative work?', [[3, 'What is the proposed solution?'], [4, 'Can we see it working?']]],
        ['ACT III', 'Proof', 'Can we trust it?', [[5, 'How do we know it works?'], [6, 'What are its limits?'], [7, 'What can we conclude?']]],
      ];
      const ax = [0.6, 4.75, 8.9], aw = 3.83;
      ACTS.forEach(([act, word, drive, qs], a) => {
        const x = ax[a];
        els.push(card(`!!act${a}`, x, 1.55, aw, 5.15, { fill: { color: C.background2 }, line: hair(C.accent1, a === 1 ? 35 : 70, a === 1 ? 1.25 : 1) }));
        els.push(T(`!!act${a}-k`, act, { x: x + 0.3, y: 1.75, w: 2, h: 0.3, fontFace: MONO, fontSize: 12, bold: true, color: C.accent1, charSpacing: 3 }));
        els.push(T(`!!act${a}-w`, word, { x: x + 0.3, y: 2.05, w: aw - 0.6, h: 0.75, fontFace: HEAD, fontSize: 40, color: C.text1 }));
        els.push(T(`!!act${a}-d`, drive, { x: x + 0.3, y: 2.82, w: aw - 0.6, h: 0.42, fontSize: 14.5, italic: true, color: C.accent1 }));
        els.push(S(`!!act${a}-hr`, 'line', { x: x + 0.3, y: 3.42, w: aw - 0.6, h: 0, line: hair(C.text1, 85, 0.75) }));
        // the section questions, threaded on a thin line
        els.push(S(`!!act${a}-thr`, 'line', { x: x + 0.42, y: 3.78, w: 0, h: (qs.length - 1) * 0.92, line: hair(C.accent1, 60, 1.25) }));
        qs.forEach(([si, q], k) => {
          const y = 3.62 + k * 0.92, demo = si === 4, col = demo ? C.accent2 : C.accent1;
          els.push(S(`!!act${a}-q${k}-dot`, 'ellipse', { x: x + 0.34, y: y + 0.08, w: 0.17, h: 0.17, fill: { color: col }, line: { type: 'none' } }));
          els.push(T(`!!act${a}-q${k}`, [
            { text: `0x${SECS[si].id}  ${SECS[si].label}`, options: { fontFace: MONO, fontSize: 10, bold: true, color: demo ? C.accent2 : C.text2, breakLine: true, charSpacing: 1 } },
            { text: q, options: { fontSize: 13.5, color: C.text1 } },
            ...(demo ? [{ text: '   5 min', options: { fontFace: MONO, fontSize: 11, bold: true, color: C.accent2 } }] : []),
          ], { x: x + 0.7, y, w: aw - 0.95, h: 0.8, valign: 'top', _link: si }));
        });
        if (a < 2) els.push(arrow(`!!act${a}-to`, x + aw + 0.03, 2.4, 0.26, 0, { color: C.accent1, width: 1.75 }));
      });
    } else {
      // the twenty minutes as one bar, each chapter as wide as the time it takes
      els.push(T('!!rm-title', 'Roadmap', { x: 0.6, y: 0.68, w: 12.1, h: 0.6, fontFace: HEAD, fontSize: 26, color: C.text1 }));
      const MIN = [1.7, 2.0, 1.3, 3.1, 5.0, 1.7, 0.6, 0.7], tot = MIN.reduce((a, b) => a + b, 0), BW = 12.13;
      let x = 0.6;
      for (let i = 0; i < 8; i++) {
        const w = BW * MIN[i] / tot, col = colOf(i), up = i % 2 === 0;
        els.push(S(`!!rm${i}`, 'rect', { x: x + 0.02, y: 3.55, w: w - 0.04, h: 0.75, fill: tint(col, i === 4 ? 60 : 78), line: { type: 'none' }, _link: i }));
        els.push(T(`!!rm${i}-t`, [{ text: `0${i + 1}  `, options: { color: col } }, { text: SECS[i].label, options: { color: i === 4 ? C.accent2 : C.text1 } }], { x: x + w / 2 - 1.1, y: up ? 3.05 : 4.45, w: 2.2, h: 0.32, fontFace: MONO, fontSize: 11.5, bold: true, align: 'center' }));
        x += w;
      }
      els.push(T('!!rm-time', [{ text: 'about 12 minutes of talk', options: { color: C.text2 } }, { text: '   ·   ', options: { color: C.text2 } }, { text: '5 minutes of demo', options: { color: C.accent2 } }], { x: 0.6, y: 5.35, w: 12.13, h: 0.35, fontFace: MONO, fontSize: 12, bold: true, align: 'center' }));
    }
    add('Opening', els, 'roadmap', { layout: 'CV_PLAIN' });
  }

  // ===== 0x100 CONTEXT =====
  Q(0, 'who', 'Who am I?', 'First, a few words about me.');
  add('CONTEXT', [
    ...head(0, 'who', 'Who am I?'),
    ...logoTile('!!who1', 0.6, 1.75, 2.1, 1.1, ['esprit.png'], { pad: 0.16 }),
    T('!!who1-t', 'Information Technology student at ESPRIT', { x: 3.05, y: 1.82, w: 9.6, h: 0.45, fontFace: HEAD, fontSize: 21, color: C.text1 }),
    T('!!who1-d', 'Graduation project, academic year 2025/2026', { x: 3.05, y: 2.32, w: 9.6, h: 0.4, fontSize: 15, color: C.text2 }),
    ...logoTile('!!who2', 0.6, 3.25, 2.1, 1.1, ['capgemini.png'], { pad: 0.16 }),
    T('!!who2-t', 'Work and study program at Capgemini Engineering', { x: 3.05, y: 3.32, w: 9.6, h: 0.45, fontFace: HEAD, fontSize: 21, color: C.text1 }),
    T('!!who2-d', 'BMS QA tester for BMW Group, Automotive division, Capgemini Tunisia, since September 2024', { x: 3.05, y: 3.82, w: 9.6, h: 0.4, fontSize: 15, color: C.text2 }),
    S('!!who3-bg', 'roundRect', { x: 0.6, y: 4.75, w: 2.1, h: 1.1, rectRadius: 0.08, fill: tint(C.accent1, 84), line: hair(C.accent1, 55) }),
    await iconOnly('!!who3-ic', 1.3, 4.95, 0.7, 'LuRadar', C.accent1),
    T('!!who3-t', 'CANvisionNative, from the idea to the validation', { x: 3.05, y: 4.82, w: 9.6, h: 0.45, fontFace: HEAD, fontSize: 21, color: C.text1 }),
    T('!!who3-d', 'I was the only developer: design, code, models, bench rig and validation', { x: 3.05, y: 5.32, w: 9.6, h: 0.4, fontSize: 15, color: C.text2 }),
  ], 'I am an Information Technology student at ESPRIT, and this is my graduation project for 2025/2026. I follow a work and study program at Capgemini Engineering: since September 2024 I work full time as a QA tester of BMS software for BMW Group, in the Battery Management Systems team of the Automotive division in Tunisia, and I study at ESPRIT on Saturdays. I started CANvisionNative in February 2026 and was its only developer, from the first idea to the validation.');

  Q(0, 'host', 'Who is the host company?', 'Now, the host company.');
  add('CONTEXT', [
    ...head(0, 'host', 'Who is the host company?'),
    IMG('!!host-logo', { path: A('capgemini_white.png'), ...fit('capgemini_white.png', 0.6, 1.85, 5.6, 0.68, 'left') }),
    T('!!host-txt', 'The engineering and research and development branch of the Capgemini group, which offers consulting and engineering services to many industries, the automotive sector among them.', { x: 0.6, y: 2.85, w: 5.5, h: 1.3, fontSize: 15, color: C.text2 }),
    card('!!host-idea', 0.6, 4.75, 5.6, 1.5, { fill: tint(C.accent1, 88), line: hair(C.accent1, 60) }),
    await iconOnly('!!host-idea-ic', 0.85, 5.0, 0.5, 'LuLightbulb', C.accent1),
    T('!!host-idea-t', 'CANvisionNative is not a team deliverable. I started it in February 2026, alongside my job, from the difficulties of my daily validation work.', { x: 1.6, y: 4.95, w: 4.4, h: 1.1, fontSize: 14, color: C.text1, valign: 'middle' }),
    ...await (async () => {
      const rows = [
        ['LuCarFront', 'Automotive division, Capgemini Tunisia', 'Works on vehicle software systems and on embedded engineering.'],
        ['LuBatteryCharging', 'Battery Management Systems team', 'Develops and validates the embedded software of battery management functions for electric and hybrid vehicles.'],
        ['LuSearch', 'My job: BMS QA tester for BMW Group', 'Work and study program since September 2024: full time, five days a week, with classes at ESPRIT on Saturdays.'],
      ];
      const out = [];
      for (let i = 0; i < rows.length; i++) {
        const y = 1.75 + i * 1.5;
        out.push(card(`!!host-c${i}`, 6.75, y, 5.98, 1.35));
        out.push(...await iconTile(`!!host-c${i}-i`, 7.0, y + 0.3, 0.7, rows[i][0], C.accent1));
        out.push(T(`!!host-c${i}-t`, rows[i][1], { x: 7.95, y: y + 0.2, w: 4.6, h: 0.38, fontFace: HEAD, fontSize: 16, color: C.text1 }));
        out.push(T(`!!host-c${i}-d`, rows[i][2], { x: 7.95, y: y + 0.6, w: 4.6, h: 0.65, fontSize: 12.5, color: C.text2 }));
      }
      return out;
    })(),
  ], 'Capgemini Engineering is the engineering and research and development branch of the Capgemini group. I work full time in its Automotive division in Tunisia, in the BMS team, as a QA tester of BMS software for BMW Group, and I study at ESPRIT on Saturdays. This team develops and validates the embedded software of battery management functions for electric and hybrid cars.\n\nA large part of its work is checking the messages exchanged on the CAN bus: is a cell voltage, a temperature or a state of charge sent at the right rate, with a plausible value? CANvisionNative was not one of the team\'s deliverables: the idea came from the difficulties of this validation work.');

  // CAN bus
  Q(0, 'can', 'How do the computers of a car talk to each other?', 'To follow the rest of the presentation, we need one technical idea: how the computers inside a car talk to each other.');
  const busEls = async (low) => {
    const yH = low ? 6.25 : 4.05, yL = yH + 0.25;
    return [
      S('!!busH', 'line', { x: 1.25, y: yH, w: 10.85, h: 0, line: { color: C.accent1, width: 3 } }),
      S('!!busL', 'line', { x: 1.25, y: yL, w: 10.85, h: 0, line: { color: C.accent5, width: 3 } }),
      T('!!busH-l', 'CAN_H', { x: 0.45, y: yH - 0.13, w: 0.75, h: 0.26, fontFace: MONO, fontSize: 10.5, color: C.accent1, bold: true }),
      T('!!busL-l', 'CAN_L', { x: 0.45, y: yL - 0.13, w: 0.75, h: 0.26, fontFace: MONO, fontSize: 10.5, color: C.accent5, bold: true }),
    ];
  };
  {
    // The bus draws itself, the ECUs connect one by one, then the BMS (in the middle) sends a
    // frame that leaves in both directions and passes under every node: the broadcast.
    const nodes = [
      ['LuZap', 'Motor controller'], ['LuBatteryCharging', 'BMS'], ['LuDisc3', 'Brakes'],
      ['LuScanEye', 'Driver assistance'], ['LuGauge', 'Dashboard'], ['LuSatelliteDish', 'Telematics'],
    ];
    const els = [...head(0, 'can', 'How do the computers of a car talk to each other?'), ...await busEls(false)];
    const cx = [2.9, 6.67, 10.43];
    const fx = [];
    const order = [1, 0, 2, 3, 4, 5];
    for (let i = 0; i < 6; i++) {
      const top = i < 3, c = cx[i % 3], x = c - 1.25, y = top ? 1.85 : 5.0, w = 2.5, h = 1.05;
      const isBms = i === 1;
      els.push(S(`!!ecu${i}-stub`, 'line', { x: c, y: top ? y + h : 4.3, w: 0, h: top ? 4.05 - (y + h) : y - 4.3, line: hair(C.text2, 30, 1.5) }));
      els.push(card(`!!ecu${i}`, x, y, w, h, { line: isBms ? hair(C.accent1, 0, 1.5) : hair(), fill: isBms ? tint(C.accent1, 85) : { color: C.background2 } }));
      els.push(await iconOnly(`!!ecu${i}-ic`, x + 0.22, y + 0.27, 0.5, nodes[i][0], isBms ? C.accent1 : C.text1));
      els.push(T(`!!ecu${i}-t`, nodes[i][1], { x: x + 0.9, y: y + 0.2, w: 1.5, h: 0.65, fontFace: HEAD, fontSize: 14.5, color: C.text1, valign: 'middle' }));
      const t0 = 900 + order.indexOf(i) * 220;
      fx.push(...fades([`!!ecu${i}`, `!!ecu${i}-ic`, `!!ecu${i}-t`], t0, 350), { type: 'wipe', name: `!!ecu${i}-stub`, dir: top ? 'down' : 'up', dur: 300, delay: t0 + 150 });
    }
    els.push(S('!!term-l', 'rect', { x: 1.12, y: 3.93, w: 0.14, h: 0.49, fill: { color: C.background2 }, line: hair(C.text2, 20, 1) }));
    els.push(S('!!term-r', 'rect', { x: 12.08, y: 3.93, w: 0.14, h: 0.49, fill: { color: C.background2 }, line: hair(C.text2, 20, 1) }));
    els.push(T('!!term-lt', '120 Ω', { x: 12.3, y: 4.05, w: 0.8, h: 0.26, fontSize: 10.5, color: C.text2 }));
    const chip = (name, t) => ST(name, '0x3F9', { shape: pres.shapes.ROUNDED_RECTANGLE, x: 6.67 - 0.475, y: 3.97, w: 0.95, h: 0.41, rectRadius: 0.06, fill: { color: C.accent2, transparency: t }, line: { type: 'none' }, fontFace: MONO, fontSize: 11, bold: true, color: C.background1, align: 'center', valign: 'middle', margin: 0 });
    els.push(chip('!!frame-l', 30), chip('!!frame-r', 30), chip('!!frame', 0));
    els.push(T('!!can-cap', 'Each ECU broadcasts short frames on one shared two-wire bus, and every node receives every frame.', { x: 0.6, y: 6.38, w: 12.1, h: 0.4, fontSize: 15, color: C.text2, align: 'center' }));
    const tSend = 900 + 6 * 220 + 400;
    add('CONTEXT', els, 'A modern electric car contains many small computers called ECUs: the battery management system, the motor controller, the brakes, driver assistance, the dashboard, telematics. They all hang on one bus with two wires, CAN high and CAN low, with a 120 ohm resistor at each end.\n\nHere the BMS, in the middle, sends a frame with identifier 0x3F9. Watch it travel in both directions: it passes under every ECU, because every ECU receives every frame. Nobody addresses a frame to someone; each node decides from the identifier whether the frame interests it.', {
      anim: [{ trigger: 'auto', effects: [
        { type: 'wipe', name: '!!busH', dir: 'right', dur: 700, delay: 0 },
        { type: 'wipe', name: '!!busL', dir: 'right', dur: 700, delay: 120 },
        ...fades(['!!busH-l', '!!busL-l', '!!term-l', '!!term-r', '!!term-lt'], 500, 300),
        ...fx,
        { type: 'pop', name: '!!frame', dur: 350, delay: tSend },
        ...fades(['!!frame-l', '!!frame-r'], tSend + 500, 100),
        { type: 'motion', name: '!!frame-l', dx: -4.85, dy: 0, dur: 4000, repeat: true, delay: tSend + 500 },
        { type: 'motion', name: '!!frame-r', dx: 4.85, dy: 0, dur: 4000, repeat: true, delay: tSend + 500 },
        { type: 'fade', name: '!!can-cap', dur: 500, delay: tSend + 900 },
      ] }],
    });
  }
  {
    // The vulnerability is shown before it is named: a genuine frame, then an identical frame
    // from an unknown device, then the three missing properties.
    const els = [...head(0, 'can', 'How do the computers of a car talk to each other?')];
    els.push(S('!!frame', 'roundRect', { x: 0.6, y: 1.42, w: 12.13, h: 1.42, rectRadius: 0.08, fill: tint(C.accent2, 90), line: hair(C.accent2, 30, 1.25) }));
    const segs = [
      ['Identifier', '11 bits: what the frame is, and its priority', 3.15, C.accent1],
      ['Length', 'number of data bytes', 1.75, C.text2],
      ['Data', 'up to 8 bytes; their meaning depends on the vehicle (DBC file)', 4.95, C.accent2],
      ['CRC', 'error check', 1.45, C.text2],
    ];
    let sx = 0.9;
    segs.forEach((s, i) => {
      els.push(card(`!!seg${i}`, sx, 1.57, s[2], 1.12, { fill: tint(hexOf(s[3]) === HX.lt2 ? C.text1 : s[3], hexOf(s[3]) === HX.lt2 ? 93 : 84), line: hair(s[3], 40), r: 0.06 }));
      els.push(T(`!!seg${i}-t`, s[0], { x: sx + 0.18, y: 1.64, w: s[2] - 0.3, h: 0.34, fontFace: HEAD, fontSize: 15, color: C.text1 }));
      els.push(T(`!!seg${i}-d`, s[1], { x: sx + 0.18, y: 2.0, w: s[2] - 0.3, h: 0.62, fontSize: 11.5, color: C.text2 }));
      sx += s[2] + 0.12;
    });
    const row = async (k, y, who, ic, color, dashed) => {
      els.push(S(`!!snd${k}`, 'roundRect', { x: 0.6, y, w: 2.25, h: 0.62, rectRadius: 0.08, fill: tint(color, 86), line: { color, width: 1.25, dashType: dashed ? 'dash' : 'solid' } }));
      els.push(IMG(`!!snd${k}-ic`, { data: await icon(ic, color), x: 0.78, y: y + 0.15, w: 0.32, h: 0.32 }));
      els.push(T(`!!snd${k}-t`, who, { x: 1.2, y, w: 1.62, h: 0.62, fontSize: 13.5, color: C.text1, valign: 'middle' }));
      els.push(arrow(`!!snd${k}-a`, 2.92, y + 0.31, 0.5, 0, { color }));
      els.push(ST(`!!fr${k}`, [{ text: '0x3F9', options: { color: C.accent1, bold: true } }, { text: '   4E 00 00 00 00 00 00 00', options: { color: C.text1 } }],
        { shape: pres.shapes.ROUNDED_RECTANGLE, x: 3.5, y, w: 4.3, h: 0.62, rectRadius: 0.08, fill: { color: C.background2 }, line: hair(C.text1, 75, 1), fontFace: MONO, fontSize: 13.5, align: 'center', valign: 'middle', margin: 0 }));
    };
    await row(0, 3.12, 'BMS', 'LuBatteryCharging', C.accent1, false);
    await row(1, 3.9, 'Unknown device', 'LuCpu', C.accent3, true);
    els.push(T('!!same', '=', { x: 7.95, y: 3.18, w: 0.6, h: 1.25, fontFace: HEAD, fontSize: 54, color: C.accent2, align: 'center', valign: 'middle' }));
    els.push(T('!!same-t', [{ text: 'Same identifier, same bytes.', options: { bold: true, color: C.text1, breakLine: true } }, { text: 'Nothing in the frame tells the receivers who sent it.', options: { color: C.text2 } }],
      { x: 8.7, y: 3.12, w: 4.03, h: 1.4, fontSize: 14.5, valign: 'middle' }));
    const miss = [
      ['LuUserX', 'NO SENDER IDENTITY', 'A frame does not say which ECU sent it.'],
      ['LuKeyRound', 'NO AUTHENTICATION', 'Any node can send any identifier.'],
      ['LuLockOpen', 'NO ENCRYPTION', 'Every node reads every frame.'],
    ];
    const missFx = [];
    for (let i = 0; i < 3; i++) {
      const x = 0.6 + i * 4.11;
      els.push(card(`!!miss${i}`, x, 4.85, 3.91, 1.0, { fill: tint(C.accent3, 88), line: hair(C.accent3, 55) }));
      els.push(IMG(`!!miss${i}-ic`, { data: await icon(miss[i][0], C.accent3), x: x + 0.25, y: 5.12, w: 0.46, h: 0.46 }));
      els.push(T(`!!miss${i}-t`, miss[i][1], { x: x + 0.95, y: 4.97, w: 2.85, h: 0.34, fontFace: MONO, fontSize: 13.5, bold: true, color: C.accent3, charSpacing: 1 }));
      els.push(T(`!!miss${i}-d`, miss[i][2], { x: x + 0.95, y: 5.33, w: 2.85, h: 0.42, fontSize: 12.5, color: C.text2 }));
      missFx.push(...fades([`!!miss${i}`, `!!miss${i}-ic`, `!!miss${i}-t`, `!!miss${i}-d`], i * 450, 350));
    }
    els.push(T('!!can-concl', 'The bus cannot tell a genuine frame from a forged one, or from a faulty one.', { x: 0.6, y: 6.05, w: 12.1, h: 0.45, fontFace: HEAD, fontSize: 19, color: C.text1, align: 'center' }));
    els.push(T('!!can-src', 'CAN protocol: ISO 11898. Shown on real cars by Koscher et al. (2010) and Miller and Valasek (2015).', { x: 0.6, y: 6.55, w: 12.1, h: 0.3, fontSize: 11, color: C.text2, align: 'center' }));
    const rowFx = (k) => [...fades([`!!snd${k}`, `!!snd${k}-ic`, `!!snd${k}-t`], 0, 300), { type: 'wipe', name: `!!snd${k}-a`, dir: 'right', dur: 300, delay: 300 }, { type: 'wipe', name: `!!fr${k}`, dir: 'right', dur: 550, delay: 550 }];
    add('CONTEXT', els, 'Let us zoom into one frame. It has an identifier, which says what the message is and also gives its priority on the bus. Then the length, up to 8 bytes of data, whose meaning depends on the vehicle and is described in a DBC file, and a CRC to detect transmission errors.\n\nHere is the BMS sending its frame 0x3F9. [CLICK] Now a device we do not know sends exactly the same frame: same identifier, same bytes. For every receiver on the bus, the two are identical. [CLICK] This is because a CAN frame has no sender identity, no authentication and no encryption. So the bus cannot tell a genuine frame from a forged one, or from one sent by a faulty ECU. Security researchers have shown this many times on real cars.', {
      anim: [
        { trigger: 'auto', effects: rowFx(0) },
        { trigger: 'click', effects: [...rowFx(1), { type: 'pop', name: '!!same', dur: 350, delay: 1150 }, { type: 'fade', name: '!!same-t', dur: 450, delay: 1350 }] },
        { trigger: 'click', effects: [...missFx, ...fades(['!!can-concl'], 1500, 500), ...fades(['!!can-src'], 1800, 400)] },
      ],
    });
  }

  // ===== 0x200 PROBLEM =====
  Q(1, 'prob', 'What are the problems?', 'So, what problems did the project start from?');
  const PROBLEMS = [
    ['LuEyeOff', 'No live view of the traffic', 'Raw frames say what happened, not whether it should have happened.'],
    ['LuHistory', 'Weak replay', 'Tools replay frames without judging them, or accept only a few log formats.'],
    ['LuPuzzle', 'Scattered tools', 'An analyser, a diagnostic scanner and a spreadsheet, for one investigation.'],
    ['LuMessageCircleQuestion', 'Alerts without explanation', 'A bare number, with no cause and no next step.'],
  ];
  // Problems slide. PROB=alerts|big|diagram|cards picks the design (cards is the first version).
  const PROB = process.env.PROB || 'alerts';
  const PROB_NOTES = 'Four problems of day to day BMS validation work motivated the project. [CLICK] First, no live view: reading raw frames tells you what happened, not whether it should have happened. [CLICK] Second, weak replay: the usual tools replay frames without judging them, or accept only a few log formats. [CLICK] Third, scattered tools: one investigation needs an analyser, a diagnostic scanner and a spreadsheet. [CLICK] Fourth, when a tool does flag something, it is a bare number, with no cause and no next step.\n\n[CLICK] Underneath all four, the CAN protocol has no security, so a toolchain that does not watch the bus cannot notice a malicious frame any more than a faulty one. Security is a real motivation, but the first goal is a clear view of the bus.';
  const SEC_LINE = 'A toolchain that does not watch the bus cannot notice a malicious frame any more than a faulty one. A real but secondary motivation.';
  if (PROB === 'alerts') {
    // The problems arrive as alerts in a panel styled like the application's alert list.
    const els = [...head(1, 'prob', 'What are the problems?')];
    els.push(card('!!al-panel', 0.6, 1.5, 12.13, 5.25, { fill: { color: C.background2 }, line: hair(C.accent2, 62, 1), r: 0.08 }));
    els.push(S('!!al-dot', 'ellipse', { x: 0.9, y: 1.77, w: 0.12, h: 0.12, fill: { color: C.accent2 }, line: { type: 'none' } }));
    els.push(T('!!al-h', [{ text: 'OPEN ISSUES', options: { color: C.text1 } }, { text: '  ·  day to day BMS validation work', options: { color: C.text2 } }], { x: 1.12, y: 1.66, w: 8, h: 0.34, fontFace: MONO, fontSize: 11.5, bold: true, valign: 'middle' }));
    const cx_ = { t: 0.9, s: 1.72, p: 3.2, d: 7.45 };
    [['TIME', cx_.t], ['TYPE', cx_.s], ['PROBLEM', cx_.p], ['WHAT HAPPENS TODAY', cx_.d]].forEach(([t, x], i) => els.push(T(`!!al-c${i}`, t, { x, y: 2.15, w: 3, h: 0.25, fontFace: MONO, fontSize: 9.5, bold: true, color: C.text2, charSpacing: 1 })));
    els.push(S('!!al-hr', 'line', { x: 0.9, y: 2.47, w: 11.55, h: 0, line: hair(C.text1, 85, 0.75) }));
    const R = [...PROBLEMS.map((p) => ['WARNING', p[1].toUpperCase(), p[2]]), ['SECURITY', 'CAN HAS NO SECURITY', SEC_LINE]];
    const counter = (k) => ST(`!!al-n${k}`, `${k} OPEN`, { shape: pres.shapes.ROUNDED_RECTANGLE, x: 11.25, y: 1.68, w: 1.2, h: 0.32, rectRadius: 0.16, fill: tint(k ? C.accent2 : C.text1, k ? 80 : 92), line: hair(k ? C.accent2 : C.text2, 40), fontFace: MONO, fontSize: 10, bold: true, color: k ? C.accent2 : C.text2, align: 'center', valign: 'middle', margin: 0 });
    els.push(counter(0));
    const groups = [];
    R.forEach(([sev, title, det], k) => {
      const y = 2.6 + k * 0.8, col = sev === 'SECURITY' ? C.accent3 : C.accent2;
      const names = [`!!al${k}-t`, `!!al${k}-s`, `!!al${k}-p`, `!!al${k}-d`];
      els.push(T(names[0], `00:0${k + 1}`, { x: cx_.t, y, w: 0.8, h: 0.62, fontFace: MONO, fontSize: 11, color: C.text2, valign: 'middle' }));
      els.push(ST(names[1], sev, { shape: pres.shapes.ROUNDED_RECTANGLE, x: cx_.s, y: y + 0.15, w: 1.25, h: 0.32, rectRadius: 0.16, fill: tint(col, 80), line: hair(col, 35), fontFace: MONO, fontSize: 9.5, bold: true, color: col, align: 'center', valign: 'middle', margin: 0 }));
      els.push(T(names[2], title, { x: cx_.p, y, w: 4.15, h: 0.62, fontFace: MONO, fontSize: 14, bold: true, color: k === 4 ? C.accent3 : C.text1, valign: 'middle' }));
      els.push(T(names[3], det, { x: cx_.d, y, w: 5.05, h: 0.62, fontSize: 12.5, color: C.text2, valign: 'middle' }));
      if (k < R.length - 1) { els.push(S(`!!al${k}-hr`, 'line', { x: 0.9, y: y + 0.71, w: 11.55, h: 0, line: hair(C.text1, 90, 0.5) })); names.push(`!!al${k}-hr`); }
      els.push(counter(k + 1));
      groups.push({ trigger: 'click', effects: [
        ...fades(names, 0, 350), { type: 'pulse', name: names[1], scale: 1.12, dur: 220, delay: 350 },
        { type: 'fadeout', name: `!!al-n${k}`, dur: 150, delay: 0 }, { type: 'fade', name: `!!al-n${k + 1}`, dur: 200, delay: 120 },
      ] });
    });
    add('PROBLEM', els, PROB_NOTES, { anim: groups });
  } else if (PROB === 'big') {
    // One problem at a time in large type; a numbered list on the left lights up as we go.
    const els = [...head(1, 'prob', 'What are the problems?')];
    const items = [...PROBLEMS.map((p) => [p[1], p[2]]), ['CAN has no security', SEC_LINE]];
    els.push(S('!!bg-div', 'line', { x: 4.85, y: 1.75, w: 0, h: 4.7, line: hair(C.text1, 85, 1) }));
    const groups = [];
    items.forEach(([t, d], k) => {
      const y = 1.85 + k * 0.82, red = k === 4;
      els.push(T(`!!bg${k}-l`, [{ text: `0${k + 1}  `, options: { color: C.text2 } }, { text: t.toUpperCase(), options: { color: C.text2 } }], { x: 0.6, y, w: 4.1, h: 0.62, fontFace: MONO, fontSize: 12, bold: true, valign: 'middle' }));
      els.push(T(`!!bg${k}-on`, [{ text: `0${k + 1}  `, options: { color: red ? C.accent3 : C.accent2 } }, { text: t.toUpperCase(), options: { color: C.text1 } }], { x: 0.6, y, w: 4.1, h: 0.62, fontFace: MONO, fontSize: 12, bold: true, valign: 'middle' }));
      els.push(T(`!!bg${k}-t`, t, { x: 5.3, y: 2.25, w: 7.4, h: 1.5, fontFace: HEAD, fontSize: 40, color: red ? C.accent3 : C.text1, valign: 'bottom', lineSpacingMultiple: 0.95 }));
      els.push(T(`!!bg${k}-d`, d, { x: 5.3, y: 3.95, w: 7.2, h: 1.2, fontSize: 18, color: C.text2 }));
      const fx = [{ type: 'fade', name: `!!bg${k}-on`, dur: 300, delay: 0 }, ...fades([`!!bg${k}-t`, `!!bg${k}-d`], 250, 450)];
      if (k > 0) fx.push({ type: 'fadeout', name: `!!bg${k - 1}-t`, dur: 200, delay: 0 }, { type: 'fadeout', name: `!!bg${k - 1}-d`, dur: 200, delay: 0 });
      groups.push({ trigger: 'click', effects: fx });
    });
    add('PROBLEM', els, PROB_NOTES, { anim: groups });
  } else if (PROB === 'diagram') {
    // The engineer between disconnected tools; each problem is pinned where it happens.
    const els = [...head(1, 'prob', 'What are the problems?')];
    const E = [6.67, 4.0];
    const tools = [['LuActivity', 'CAN analyser', 1.0, 1.7], ['LuSearch', 'Diagnostic scanner', 9.83, 1.7], ['LuFileSpreadsheet', 'Spreadsheet', 1.0, 5.55], ['LuFileText', 'Raw log files', 9.83, 5.55]];
    const tc = tools.map(([, , x, y]) => [x + 1.25, y + 0.42]);
    tc.forEach(([x, y], i) => {
      const left = x < E[0], up = y < E[1];
      els.push(S(`!!dg-l${i}`, 'line', { x: Math.min(x, E[0]), y: Math.min(y, E[1]), w: Math.abs(x - E[0]), h: Math.abs(y - E[1]), flipV: left !== up, line: { color: C.text2, width: 1.25, dashType: 'dash', transparency: 30 } }));
    });
    els.push(card('!!dg-eng-bg', E[0] - 1.25, E[1] - 0.47, 2.5, 0.94, { fill: { color: C.background1 }, line: { type: 'none' } }));
    els.push(card('!!dg-eng', E[0] - 1.25, E[1] - 0.47, 2.5, 0.94, { fill: tint(C.accent1, 86), line: hair(C.accent1, 30, 1.5) }));
    els.push(IMG('!!dg-eng-i', { data: await icon('LuUser', C.accent1), x: E[0] - 1.02, y: E[1] - 0.22, w: 0.44, h: 0.44 }));
    els.push(T('!!dg-eng-t', 'BMS engineer', { x: E[0] - 0.45, y: E[1] - 0.47, w: 1.65, h: 0.94, fontFace: HEAD, fontSize: 15, color: C.text1, valign: 'middle' }));
    for (let i = 0; i < 4; i++) {
      const [ic, t, x, y] = tools[i];
      els.push(card(`!!dg-t${i}`, x, y, 2.5, 0.84, { fill: { color: C.background2 }, line: hair(C.text1, 75, 1) }));
      els.push(IMG(`!!dg-t${i}-i`, { data: await icon(ic, C.text1), x: x + 0.22, y: y + 0.22, w: 0.4, h: 0.4 }));
      els.push(T(`!!dg-t${i}-t`, t, { x: x + 0.78, y, w: 1.65, h: 0.84, fontSize: 14, color: C.text1, valign: 'middle' }));
    }
    // problem pins on the links: [link, title, line]
    const pins = [[3, 'NO LIVE VIEW', 'what happened, not whether it should have'], [0, 'WEAK REPLAY', 'frames replayed without being judged'], [2, 'SCATTERED TOOLS', 'three tools for one investigation'], [1, 'ALERTS WITHOUT EXPLANATION', 'a bare number, no cause, no next step']];
    const groups = [];
    pins.forEach(([li, t, d], k) => {
      const mx = (tc[li][0] + E[0]) / 2, my = (tc[li][1] + E[1]) / 2;
      const w = 3.05, x = mx - w / 2, y = my - 0.36;
      els.push(card(`!!dg-p${k}`, x, y, w, 0.72, { fill: { color: C.background1 }, line: hair(C.accent2, 25, 1.25), r: 0.08 }));
      els.push(ST(`!!dg-p${k}-n`, String(k + 1), { shape: pres.shapes.OVAL, x: x + 0.12, y: y + 0.17, w: 0.38, h: 0.38, fill: tint(C.accent2, 75), line: { type: 'none' }, fontFace: MONO, fontSize: 11, bold: true, color: C.accent2, align: 'center', valign: 'middle', margin: 0 }));
      els.push(T(`!!dg-p${k}-t`, [{ text: t, options: { fontFace: MONO, bold: true, color: C.accent2, fontSize: 11, breakLine: true } }, { text: d, options: { color: C.text2, fontSize: 10.5 } }], { x: x + 0.6, y: y + 0.04, w: w - 0.68, h: 0.64, valign: 'middle' }));
      groups.push({ trigger: 'click', effects: [{ type: 'pop', name: `!!dg-p${k}`, dur: 300, delay: 0 }, ...fades([`!!dg-p${k}-n`, `!!dg-p${k}-t`], 150, 300)] });
    });
    els.push(T('!!dg-sec', [{ text: 'Underneath: CAN has no security. ', options: { bold: true, color: C.accent3 } }, { text: SEC_LINE, options: { color: C.text2 } }], { x: 0.6, y: 6.55, w: 12.13, h: 0.4, fontSize: 12, align: 'center', valign: 'middle' }));
    groups.push({ trigger: 'click', effects: [{ type: 'fade', name: '!!dg-sec', dur: 500, delay: 0 }] });
    add('PROBLEM', els, PROB_NOTES, { anim: groups });
  } else
  {
    const els = [...head(1, 'prob', 'What are the problems?')];
    const groups = [];
    for (let i = 0; i < 4; i++) {
      const x = i % 2 ? 6.75 : 0.6, y = i < 2 ? 1.55 : 3.4;
      els.push(card(`!!pb${i}`, x, y, 5.98, 1.65));
      els.push(...await iconTile(`!!pb${i}-i`, x + 0.3, y + 0.3, 0.72, PROBLEMS[i][0], C.accent2));
      els.push(T(`!!pb${i}-t`, PROBLEMS[i][1], { x: x + 1.3, y: y + 0.27, w: 4.45, h: 0.42, fontFace: HEAD, fontSize: 18, color: C.text1 }));
      els.push(T(`!!pb${i}-d`, PROBLEMS[i][2], { x: x + 1.3, y: y + 0.75, w: 4.45, h: 0.75, fontSize: 13.5, color: C.text2 }));
      groups.push({ trigger: 'click', effects: fades([`!!pb${i}`, `!!pb${i}-i-bg`, `!!pb${i}-i-ic`, `!!pb${i}-t`, `!!pb${i}-d`], 0, 400) });
    }
    els.push(card('!!pb-sec', 0.6, 5.3, 12.13, 1.3, { fill: tint(C.accent3, 88), line: hair(C.accent3, 55) }));
    els.push(...await iconTile('!!pb-sec-i', 0.9, 5.59, 0.72, 'LuShieldOff', C.accent3));
    els.push(T('!!pb-sec-t', [
      { text: 'Underneath all four: CAN has no security. ', options: { bold: true, color: C.text1 } },
      { text: 'A toolchain that does not watch the bus cannot notice a malicious frame any more than a faulty one. Security is a real motivation, but a secondary one.', options: { color: C.text2 } },
    ], { x: 1.9, y: 5.4, w: 10.6, h: 1.1, fontSize: 14.5, valign: 'middle' }));
    groups.push({ trigger: 'click', effects: fades(['!!pb-sec', '!!pb-sec-i-bg', '!!pb-sec-i-ic', '!!pb-sec-t'], 0, 400) });
    add('PROBLEM', els, 'Four problems of day to day BMS validation work motivated the project. [CLICK] First, no live view: reading raw frames tells you what happened, not whether it should have happened. [CLICK] Second, weak replay: the usual tools replay frames without judging them, or accept only a few log formats. [CLICK] Third, scattered tools: one investigation needs an analyser, a diagnostic scanner and a spreadsheet. [CLICK] Fourth, when a tool does flag something, it is a bare number, with no cause and no next step.\n\n[CLICK] Underneath all four, the CAN protocol has no security, so a toolchain that does not watch the bus cannot notice a malicious frame any more than a faulty one. Security is a real motivation, but the first goal is a clear view of the bus.', { anim: groups });
  }
  Q(1, 'exist', 'What already exists?', 'Before building anything, I looked at what already exists.');
  {
    const els = [...head(1, 'exist', 'What already exists?')];
    const X = [
      { t: 'CAN analysers', logos: ['vector.png'], good: 'Capture, DBC decoding and replay. The professional standard (CANoe, CANalyzer).', miss: 'No judgement on whether a frame is normal for this vehicle.' },
      { t: 'Intrusion detection research', icon: 'LuFlaskConical', good: 'Learns normal traffic and flags what deviates from it.', miss: 'One signal, aims at attacks, rarely transfers to another vehicle, no explanation.' },
      { t: 'Open source viewers', logos: ['savvycan.png', 'linux.png'], good: 'Lightweight and open source: SavvyCAN, candump.', miss: 'Little control over replay, no notion of abnormal.' },
      { t: 'Diagnostic scanners', logos: ['sae.png', 'iso.png'], good: 'Standard requests (OBD, UDS) to known ECUs.', miss: 'Only see what they ask for, not the whole bus.' },
    ];
    const fx = [];
    for (let i = 0; i < 4; i++) {
      const x = 0.6 + i * 3.077, y = 1.5, w = 2.9;
      const names = [`!!ex${i}`];
      els.push(card(`!!ex${i}`, x, y, w, 3.9));
      if (X[i].logos) { const lt = logoTile(`!!ex${i}-lg`, x + 0.2, y + 0.2, w - 0.4, 0.78, X[i].logos, { pad: 0.13 }); els.push(...lt); names.push(...lt.map((e) => e.name)); }
      else {
        els.push(S(`!!ex${i}-lg-bg`, 'roundRect', { x: x + 0.2, y: y + 0.2, w: w - 0.4, h: 0.78, rectRadius: 0.08, fill: tint(C.accent6, 84), line: hair(C.accent6, 55) }));
        els.push(await iconOnly(`!!ex${i}-lg-ic`, x + w / 2 - 0.25, y + 0.34, 0.5, X[i].icon, C.accent6));
        names.push(`!!ex${i}-lg-bg`, `!!ex${i}-lg-ic`);
      }
      els.push(T(`!!ex${i}-t`, X[i].t, { x: x + 0.2, y: y + 1.12, w: w - 0.35, h: 0.62, fontFace: HEAD, fontSize: 15.5, color: C.text1, valign: 'top' }));
      els.push(T(`!!ex${i}-gl`, 'GOOD AT', { x: x + 0.2, y: y + 1.8, w: w - 0.4, h: 0.24, fontFace: MONO, fontSize: 10, bold: true, color: C.accent4, charSpacing: 1 }));
      els.push(T(`!!ex${i}-g`, X[i].good, { x: x + 0.2, y: y + 2.05, w: w - 0.35, h: 0.78, fontSize: 12, color: C.text1 }));
      els.push(T(`!!ex${i}-ml`, 'MISSING', { x: x + 0.2, y: y + 2.86, w: w - 0.4, h: 0.24, fontFace: MONO, fontSize: 10, bold: true, color: C.accent3, charSpacing: 1 }));
      els.push(T(`!!ex${i}-m`, X[i].miss, { x: x + 0.2, y: y + 3.1, w: w - 0.35, h: 0.75, fontSize: 12, color: C.text2 }));
      names.push(`!!ex${i}-t`, `!!ex${i}-gl`, `!!ex${i}-g`, `!!ex${i}-ml`, `!!ex${i}-m`);
      fx.push(...fades(names, i * 300, 400));
    }
    els.push(card('!!ex-us', 0.6, 5.62, 12.13, 1.05, { fill: tint(C.accent2, 88), line: hair(C.accent2, 50) }));
    els.push(await iconOnly('!!ex-us-i', 0.9, 5.9, 0.5, 'LuPuzzle', C.accent2));
    els.push(T('!!ex-us-t', [
      { text: 'Each tool covers one part. ', options: { bold: true, color: C.text1 } },
      { text: 'None of them combines decoding, replay, live monitoring, detection and explanation in one workflow.', options: { color: C.text2 } },
    ], { x: 1.65, y: 5.62, w: 10.9, h: 1.05, fontSize: 14.5, valign: 'middle' }));
    fx.push(...fades(['!!ex-us', '!!ex-us-i', '!!ex-us-t'], 1600, 450));
    add('PROBLEM', els, 'The existing solutions fall into four families.\n\nCAN analysers such as Vector CANoe are the professional standard: they capture, decode with a DBC file and replay, but they do not judge whether a frame is normal for this vehicle without custom scripts.\n\nIntrusion detection research learns normal traffic and flags deviations, which is the family our detection belongs to. But these detectors usually rely on one signal, aim at attacks, rarely transfer to another vehicle, and do not explain their alerts.\n\nOpen source viewers like SavvyCAN and candump are light, but have no notion of abnormal. Diagnostic scanners using OBD or UDS only see what they ask for.\n\nEach tool covers one part; none of them puts decoding, replay, live monitoring, detection and explanation in one workflow.', { anim: [{ trigger: 'auto', effects: fx }] });
  }
  const STMT = 'How can we give a BMS engineer one view of the CAN traffic, adapted to each vehicle, that explains its own alerts?';
  // Problem statement, kept simple: the question alone, large and centred; then (Morph) it moves
  // to the top and the three needs rise into view one after the other, with the problems they answer.
  const hiRun = (t) => ({ text: t, options: { color: C.accent1 } });
  const STMT_RUNS = [
    { text: 'How can we give a BMS engineer ', options: { color: C.text1 } }, hiRun('one view of the CAN traffic'), { text: ', ', options: { color: C.text1 } },
    hiRun('adapted to each vehicle'), { text: ', that ', options: { color: C.text1 } }, hiRun('explains its own alerts'), { text: '?', options: { color: C.text1 } },
  ];
  {
    const els = [tagEl(1, 'h'), ...progress(1, 'c')];
    els.push(T('!!ps-label', 'PROBLEM STATEMENT', { x: 0.6, y: 2.05, w: 12.13, h: 0.34, fontFace: MONO, fontSize: 14, bold: true, color: C.accent2, align: 'center', charSpacing: 3 }));
    els.push(T('!!stmt', STMT_RUNS, { x: 0.9, y: 2.55, w: 11.53, h: 2.0, fontFace: HEAD, fontSize: 36, align: 'center', valign: 'middle' }));
    els.push(T('!!ps-proof', '… and prove that it works on real recordings.', { x: 0.9, y: 4.65, w: 11.53, h: 0.45, fontSize: 18, italic: true, color: C.text2, align: 'center' }));
    add('PROBLEM', els, 'stmt-hero');
  }
  {
    const els = [tagEl(1, 'h'), ...progress(1, 'c')];
    els.push(T('!!ps-label', 'PROBLEM STATEMENT', { x: 0.6, y: 0.82, w: 12.13, h: 0.32, fontFace: MONO, fontSize: 13, bold: true, color: C.accent2, align: 'center', charSpacing: 3 }));
    els.push(T('!!stmt', STMT_RUNS, { x: 0.9, y: 1.3, w: 11.53, h: 1.6, fontFace: HEAD, fontSize: 28, align: 'center', valign: 'middle' }));
    els.push(T('!!ps-proof', '… and prove that it works on real recordings.', { x: 0.9, y: 2.95, w: 11.53, h: 0.4, fontSize: 15, italic: true, color: C.text2, align: 'center' }));
    const NEEDS = [
      ['ONE VIEW OF THE TRAFFIC', ['NO LIVE VIEW', 'WEAK REPLAY', 'SCATTERED TOOLS'], ''],
      ['ADAPTED TO EACH VEHICLE', ['MODELS RARELY TRANSFER'], 'from one vehicle to another'],
      ['EXPLAINS ITS OWN ALERTS', ['ALERTS WITHOUT EXPLANATION'], 'a bare number, with no cause'],
    ];
    const colX = [0.6, 4.715, 8.83], colW = 3.9, cardY = 3.75;
    const fx = [];
    NEEDS.forEach(([h, chips, note], c) => {
      const names = [`!!ps-c${c}`, `!!ps-c${c}-h`, `!!ps-c${c}-a`];
      els.push(card(`!!ps-c${c}`, colX[c], cardY, colW, 2.75, { fill: tint(C.accent1, 92), line: hair(C.accent1, 55, 1) }));
      els.push(T(`!!ps-c${c}-h`, h, { x: colX[c] + 0.2, y: cardY + 0.16, w: colW - 0.4, h: 0.34, fontFace: MONO, fontSize: 13, bold: true, color: C.accent1, charSpacing: 1 }));
      els.push(T(`!!ps-c${c}-a`, 'ANSWERS', { x: colX[c] + 0.2, y: cardY + 0.55, w: 2, h: 0.24, fontFace: MONO, fontSize: 9.5, bold: true, color: C.text2, charSpacing: 2 }));
      chips.forEach((t, r) => {
        els.push(ST(`!!ps-c${c}-k${r}`, t, { shape: pres.shapes.ROUNDED_RECTANGLE, x: colX[c] + 0.2, y: cardY + 0.88 + r * 0.55, w: 3.5, h: 0.42, rectRadius: 0.08, fill: { color: C.background2 }, line: hair(C.accent2, 30, 1.25), fontFace: MONO, fontSize: 11.5, bold: true, color: C.accent2, align: 'center', valign: 'middle', margin: 0 }));
        names.push(`!!ps-c${c}-k${r}`);
      });
      if (note) { els.push(T(`!!ps-c${c}-n`, note, { x: colX[c] + 0.2, y: cardY + 1.37, w: 3.5, h: 0.3, fontSize: 11, color: C.text2, align: 'center' })); names.push(`!!ps-c${c}-n`); }
      names.forEach((n) => fx.push({ type: 'flyfrom', name: n, dx: 0, dy: 0.35, dur: 500, delay: 300 + c * 350 }));
    });
    add('PROBLEM', els, 'stmt-needs', { anim: [{ trigger: 'auto', effects: fx }] });
  }
  {
    // The answer emerges: the question moves up and CANvisionNative appears with the eye, moving
    // like on the title slide.
    const hero = await makeHero('eye', { sharp, HX, C, S, IMG, ST, tint, hair, pres }, { cx: 3.45, cy: 4.4, w: 5.6 });
    const els = [tagEl(1, 'h'), ...progress(1, 'c'), ...hero.els];
    els.push(T('!!stmt', STMT, { x: 0.6, y: 0.68, w: 12.1, h: 0.75, fontFace: HEAD, fontSize: 18, color: C.text2, align: 'left', valign: 'top' }));
    els.push(T('!!idea-k', 'THE IDEA', { x: 6.75, y: 2.05, w: 5.9, h: 0.3, fontFace: MONO, fontSize: 12, bold: true, color: C.accent1, charSpacing: 2 }));
    els.push(T('!!idea-name', [{ text: 'CANvision', options: { color: C.text1 } }, { text: 'Native', options: { color: C.accent1 } }], { x: 6.75, y: 2.35, w: 6.0, h: 0.85, fontFace: HEAD, fontSize: 42 }));
    els.push(T('!!idea-def', 'One platform where a BMS engineer replays, monitors and understands the CAN traffic of a vehicle.', { x: 6.75, y: 3.25, w: 5.95, h: 0.75, fontSize: 16, color: C.text2 }));
    const rows = [['LuLayers', 'One view', 'replay, live monitoring and detection together'], ['LuCarFront', 'Adapted to each vehicle', 'its own models and its own DBC file'], ['LuMessageSquareText', 'Explains its own alerts', 'in plain language, next to the score']];
    // the eye has no entrance effect: the Morph fades it in, and it moves by itself
    const fx = [...fades(['!!idea-k', '!!idea-name'], 600, 500), { type: 'fade', name: '!!idea-def', dur: 500, delay: 900 }];
    for (let k = 0; k < 3; k++) {
      const y = 4.3 + k * 0.72;
      els.push(...await iconTile(`!!idea${k}`, 6.75, y, 0.56, rows[k][0], C.accent1));
      els.push(T(`!!idea${k}-t`, [{ text: rows[k][1], options: { bold: true, color: C.text1, breakLine: true } }, { text: rows[k][2], options: { color: C.text2, fontSize: 12.5 } }], { x: 7.5, y: y - 0.06, w: 5.2, h: 0.68, fontSize: 14.5, valign: 'middle' }));
      fx.push(...fades([`!!idea${k}-bg`, `!!idea${k}-ic`, `!!idea${k}-t`], 1300 + k * 300, 400));
    }
    add('PROBLEM', els, 'My answer to this question is CANvisionNative: one platform where a BMS engineer replays, monitors and understands the CAN traffic of a vehicle. One view instead of scattered tools; models adapted to each vehicle; and alerts that explain themselves in plain language.', { anim: [{ trigger: 'auto', effects: fx }] });
  }

  // ===== 0x300 OBJECTIVES AND REQUIREMENTS =====
  // Objectives as in the thesis (section 1.7): the general objective, then the six specific ones.
  // Then the methodology, then the requirements captured in the inception phase.
  Q(2, 'obj', 'What are the objectives?', 'What are the objectives of the project?');
  {
    const els = [...head(2, 'obj', 'What are the objectives?')];
    els.push(card('!!ob-gen', 0.6, 1.5, 12.13, 1.4, { fill: tint(C.accent1, 90), line: hair(C.accent1, 60) }));
    els.push(T('!!ob-gen-k', 'GENERAL OBJECTIVE', { x: 0.85, y: 1.64, w: 6, h: 0.28, fontFace: MONO, fontSize: 11.5, bold: true, color: C.accent1, charSpacing: 2 }));
    els.push(T('!!ob-gen-t', 'Design, build and validate a diagnostic platform for Battery Management Systems that gives an engineer one view of the CAN traffic, adapts to the vehicle being analysed, and explains its own alerts.', { x: 0.85, y: 1.98, w: 11.65, h: 0.8, fontSize: 16.5, color: C.text1 }));
    els.push(T('!!ob-spec-k', 'SPECIFIC OBJECTIVES', { x: 0.6, y: 3.15, w: 6, h: 0.28, fontFace: MONO, fontSize: 11.5, bold: true, color: C.text2, charSpacing: 2 }));
    const OB = [
      'A detection pipeline that combines a machine learning model with timing, payload and persistence checks',
      'The common log formats (CSV, MF4, candump, Vector, PCAN), a live simulator and live capture',
      'One model per vehicle, and in production only the models evaluated on a recording kept out of training',
      'A desktop client to import a log, replay it, review the anomalies and export a report',
      'An explanation layer, separate from detection, with rules and a language model',
      'A validation on real recordings with reproducible evidence, and every defect found corrected',
    ];
    const fx = [...fades(['!!ob-gen', '!!ob-gen-k', '!!ob-gen-t'], 300, 450), ...fades(['!!ob-spec-k'], 900, 400)];
    OB.forEach((t, i) => {
      const x = i < 3 ? 0.6 : 6.75, y = 3.55 + (i % 3) * 1.05;
      els.push(T(`!!ob${i}-n`, String(i + 1), { x, y: y - 0.04, w: 0.45, h: 0.5, fontFace: HEAD, fontSize: 22, color: C.accent1 }));
      els.push(T(`!!ob${i}`, t, { x: x + 0.5, y, w: 5.45, h: 0.85, fontSize: 14.5, color: C.text1 }));
      const names = [`!!ob${i}-n`, `!!ob${i}`];
      if (i % 3 < 2) { els.push(S(`!!ob${i}-r`, 'line', { x, y: y + 0.93, w: 5.98, h: 0, line: hair(C.text1, 88, 0.75) })); names.push(`!!ob${i}-r`); }
      fx.push(...fades(names, 1100 + i * 200, 400));
    });
    add(SECS[2].label, els, 'obj', { anim: [{ trigger: 'auto', effects: fx }] });
  }

  Q(2, 'method', 'How did I organize the work?', 'How did I organize the work?');
  {
    // Methodology as in the thesis (section 1.8): the Unified Process, its four phases and the
    // four iterations of the construction phase, then why it was chosen. The phases fade in in turn.
    // One timeline: the four phases on a line, the four iterations as numbered dots, one line on why.
    const els = [...head(2, 'method', 'How did I organize the work?'), sub('The Unified Process')];
    const fx = [];
    const BY = 3.45, GAP = 0.12;
    const PH = [
      ['INCEPTION', 'February', 'Use cases and risks', C.accent2, 1.75],
      ['ELABORATION', 'Feb to March', 'Architecture (M1)', C.accent6, 2.15],
      ['CONSTRUCTION', 'March to September', '', C.accent1, 6.25],
      ['TRANSITION', 'Sept to October', 'Release and report', C.accent4, 1.74],
    ];
    let x = 0.6;
    PH.forEach(([name, when, what, col, w], p) => {
      const n = [`!!ph${p}`, `!!ph${p}-w`, `!!ph${p}-bar`];
      els.push(T(`!!ph${p}`, name, { x, y: 2.45, w, h: 0.34, fontFace: MONO, fontSize: 14, bold: true, color: col, align: 'center', charSpacing: 2 }));
      els.push(T(`!!ph${p}-w`, when, { x, y: 2.85, w, h: 0.3, fontSize: 12, color: C.text2, align: 'center' }));
      els.push(S(`!!ph${p}-bar`, 'rect', { x, y: BY, w, h: 0.1, fill: { color: col }, line: { type: 'none' } }));
      if (what) { els.push(T(`!!ph${p}-d`, what, { x, y: 3.9, w, h: 0.34, fontSize: 14, color: C.text1, align: 'center' })); n.push(`!!ph${p}-d`); }
      fx.push(...fades(n, 200 + p * 450, 400));
      if (p === 2) {
        ['First pipeline', 'Validation', 'Bench rig', 'Model rebuild'].forEach((t, k) => {
          const cx = x + w * (k + 0.5) / 4;
          els.push(ST(`!!it${k}`, String(k + 1), { shape: pres.shapes.OVAL, x: cx - 0.24, y: BY + 0.05 - 0.24, w: 0.48, h: 0.48, fill: { color: C.background1 }, line: hair(C.accent1, 0, 1.75), fontFace: MONO, fontSize: 13, bold: true, color: C.accent1, align: 'center', valign: 'middle', margin: 0 }));
          els.push(T(`!!it${k}-t`, t, { x: cx - 0.78, y: 3.9, w: 1.56, h: 0.34, fontSize: 14, color: C.text1, align: 'center' }));
          fx.push(...fades([`!!it${k}`, `!!it${k}-t`], 1300 + k * 250, 350));
        });
      }
      x += w + GAP;
    });
    els.push(T('!!m-why', [{ text: 'Why: ', options: { bold: true, color: C.accent1 } }, { text: 'iterative, driven by risks, architecture first.', options: { color: C.text1 } }], { x: 0.6, y: 5.25, w: 12.13, h: 0.42, fontSize: 18, align: 'center' }));
    els.push(T('!!m-why2', 'Two unknowns at the start: how well a model generalises, and how many defects validation finds.', { x: 0.6, y: 5.75, w: 12.13, h: 0.36, fontSize: 14, color: C.text2, align: 'center' }));
    fx.push(...fades(['!!m-why', '!!m-why2'], 2600, 450));
    add(SECS[2].label, els, 'method', { anim: [{ trigger: 'auto', effects: fx }] });
  }

  // Functional requirements: three build steps
  Q(2, 'fr', 'What must the platform do?', 'From there, the functional requirements: what must the platform do?');
  {
    const FR = [
      ['LuFileInput', 'Import a recorded log', 'CSV, MF4, Vector .asc, candump .log, PCAN .txt into one frame stream'],
      ['LuCarFront', 'Choose the vehicle', 'Its own models score the frames; its DBC file decodes them'],
      ['LuPlay', 'Replay the log', 'From 0.5× to 32× real time, with progress'],
      ['LuRadar', 'Detect anomalies', 'Score each frame; report what cannot be scored, with the reason'],
      ['LuMessageSquareText', 'Explain an alert', 'Dominant signal, likely cause, what to check'],
      ['LuRadio', 'Go live', 'Simulator, or a CAN adapter through python-can; record a session'],
      ['LuFileDown', 'Export the results', 'CSV file and PDF report'],
    ];
    const node = (name, text, x, y, w, o = {}) => ST(name, text, { shape: pres.shapes.ROUNDED_RECTANGLE, x, y, w, h: 0.55, rectRadius: 0.1, fill: o.hl ? tint(C.accent1, 82) : { color: C.background2 }, line: hair(o.hl ? C.accent1 : C.text1, o.hl ? 30 : 80, 1), fontSize: 13.5, color: C.text1, align: 'center', valign: 'middle', margin: 0 });
    const pipe = (step) => {
      const e = [];
      e.push(T('!!fr-pipe-h', 'HOW THEY CHAIN', { x: 7.55, y: 1.12, w: 5.1, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: C.text2, charSpacing: 1 }));
      const Y = [1.55, 2.43, 3.31, 4.19, 5.07, 5.95], ah = 0.33;
      e.push(node('!!n-log', 'Log file', 7.55, Y[0], 2.3));
      e.push(arrow('!!a-log', 8.7, Y[0] + 0.55, 0, ah));
      e.push(node('!!n-veh', 'Vehicle: models + DBC', 8.45, Y[1], 3.3));
      if (step >= 2) {
        e.push(arrow('!!a-veh', 10.1, Y[1] + 0.55, 0, ah));
        e.push(node('!!n-rep', step >= 3 ? 'Replay or live stream' : 'Replay', 8.45, Y[2], 3.3));
        e.push(arrow('!!a-rep', 10.1, Y[2] + 0.55, 0, ah));
        e.push(node('!!n-det', 'Detection', 8.45, Y[3], 3.3, { hl: true }));
        e.push(arrow('!!a-det', 10.1, Y[3] + 0.55, 0, ah));
        e.push(node('!!n-exp', 'Explanation', 8.45, Y[4], 3.3));
      }
      if (step >= 3) {
        e.push(node('!!n-live', 'Simulator or adapter', 10.35, Y[0], 2.38));
        e.push(arrow('!!a-live', 11.5, Y[0] + 0.55, 0, ah));
        e.push(arrow('!!a-exp', 10.1, Y[4] + 0.55, 0, ah));
        e.push(node('!!n-out', 'Export: PDF, CSV', 8.45, Y[5], 3.3));
      }
      return e;
    };
    const steps = [2, 5, 7];
    const notes = [
      'First, import a recorded log in the formats engineers actually use, CSV, MF4, Vector, candump and PCAN, and turn every one of them into the same frame stream. Then choose the vehicle: its own models score the frames, and its DBC file decodes them when one exists.',
      'Then replay the log at a chosen speed, and detect anomalies. An important point here: the frames the system cannot judge are reported, with the reason, instead of being silently counted as normal. And any alert can be explained in plain language.',
      'Finally, the platform must go live, with a simulator or a real CAN adapter through python-can, record a session, and export the results as a CSV file and a PDF report.',
    ];
    for (let s = 0; s < 3; s++) {
      const els = [...head(2, 'fr', 'What must the platform do?')];
      for (let i = 0; i < steps[s]; i++) {
        const y = 1.5 + i * 0.76;
        els.push(...await iconTile(`!!fr${i}`, 0.6, y + 0.03, 0.58, FR[i][0], C.accent1));
        els.push(T(`!!fr${i}-t`, FR[i][1], { x: 1.38, y: y - 0.01, w: 5.9, h: 0.34, fontFace: HEAD, fontSize: 15.5, color: C.text1 }));
        els.push(T(`!!fr${i}-d`, FR[i][2], { x: 1.38, y: y + 0.33, w: 5.9, h: 0.32, fontSize: 12, color: C.text2 }));
      }
      els.push(...pipe(s + 1));
      add(SECS[2].label, els, notes[s]);
    }
  }

  Q(2, 'nfr', 'How should it behave?', 'And how should the platform behave? These are the non functional requirements.');
  {
    const els = [...head(2, 'nfr', 'How should it behave?')];
    const N = [
      ['LuGauge', 'Performance', 'Offline: hundreds of thousands of frames in a few minutes. Live: keep up with the bus.'],
      ['LuBadgeCheck', 'Reliability', 'A defect is fixed with evidence, never by tuning a threshold until the numbers look better.'],
      ['LuUser', 'Usability', 'No machine learning background needed to read an alert and its explanation.'],
      ['LuFileCode', 'Format independence', 'Every log format enters the pipeline as the same frame stream.'],
      ['LuPlug', 'Extensibility', 'A new vehicle needs only a DBC file and a model folder that passes the promotion checks.'],
      ['LuLifeBuoy', 'Graceful degradation', 'No language model reachable: a rule based explanation instead of a failure.'],
    ];
    for (let i = 0; i < 6; i++) {
      const x = 0.6 + (i % 3) * 4.11, y = i < 3 ? 1.5 : 3.95;
      els.push(card(`!!nf${i}`, x, y, 3.91, 2.25));
      els.push(...await iconTile(`!!nf${i}-i`, x + 0.25, y + 0.25, 0.62, N[i][0], C.accent5));
      els.push(T(`!!nf${i}-t`, N[i][1], { x: x + 1.05, y: y + 0.3, w: 2.7, h: 0.5, fontFace: HEAD, fontSize: 17, color: C.text1, valign: 'middle' }));
      els.push(T(`!!nf${i}-d`, N[i][2], { x: x + 0.25, y: y + 1.07, w: 3.45, h: 1.05, fontSize: 13, color: C.text2 }));
    }
    els.push(T('!!nf-plat', 'Platform: Windows 10 or 11 with .NET Framework 4.8  ·  a local Python 3.11 backend  ·  a python-can adapter, only for live capture', { x: 0.6, y: 6.38, w: 12.1, h: 0.35, fontSize: 12, color: C.text2, align: 'center' }));
    add(SECS[2].label, els, 'Six non functional requirements. Performance: an offline analysis of hundreds of thousands of frames in a few minutes, and live scoring that keeps up with the bus; we will see that the second one is only met for slow buses. Reliability: a defect is fixed with evidence, never by tuning a threshold. Usability: no machine learning background needed. Format independence: every format becomes the same frame stream. Extensibility: a new vehicle only needs a DBC file and a model that passes the checks. And graceful degradation: without a language model, the explanation falls back to rules.');
  }

  // ===== 0x400 SOLUTION =====
  Q(3, 'sol', 'What is the proposed solution?', 'Now, the proposed solution.');
  {
    // Architecture, built stage by stage. A frame chip moves under the stages as the data does;
    // the stage being discussed is lit and the previous ones are dimmed, then everything lights
    // up and the backend bracket shows which stages run in the local Python backend.
    const els = [...head(3, 'sol', 'What is the proposed solution?')];
    const ST_ = [
      ['!!st0', 'LuFileInput', 'Traffic sources', 'CSV, MF4, ASC, candump and PCAN logs, a simulator or a CAN adapter'],
      ['!!st1', 'LuFileCode', 'Parser', 'one frame stream: time, identifier, payload · DBC decoding'],
      ['!!st2', 'LuActivity', 'Features', '9 per identifier, over a window of 10 frames'],
      ['!!zoom', 'LuRadar', 'Detection engine', 'one Isolation Forest per identifier, plus timing, payload and persistence rules'],
      ['!!st4', 'LuServer', 'REST API', 'FastAPI · sessions in SQLite · explanations'],
      ['!!st5', 'LuMonitor', 'WPF client', '7 screens · PDF and CSV export'],
    ];
    const CAP = [
      'Three sources of frames: recorded logs in five formats, a live simulator and a real CAN adapter.',
      'Every format becomes the same frame stream; a DBC file decodes the signals when one exists.',
      'For each identifier: timing, payload change and entropy, over the last 10 frames.',
      'The model of each identifier scores the frame; timing, payload and persistence rules complete the score.',
      'FastAPI serves the results to the client, keeps the sessions in SQLite and writes the explanations.',
      'The desktop client shows the traffic, the alerts and their explanations, and exports PDF and CSV.',
      'Two programs on one machine: a local Python backend and a Windows client, talking over HTTP.',
    ];
    const cw = 1.82, gap = 0.24, y0 = 2.2, ch = 2.45;
    const sx = (k) => 0.6 + k * (cw + gap);
    const groups = [];
    els.push(S('!!be-box', 'roundRect', { x: sx(1) - 0.1, y: y0 - 0.32, w: 4 * cw + 3 * gap + 0.2, h: ch + 0.5, rectRadius: 0.1, fill: { color: C.accent1, transparency: 96 }, line: { color: C.accent1, width: 1, dashType: 'dash', transparency: 35 } }));
    els.push(T('!!be-box-t', 'LOCAL PYTHON BACKEND  ·  FastAPI', { x: sx(1), y: y0 - 0.62, w: 5, h: 0.26, fontFace: MONO, fontSize: 10.5, bold: true, color: C.accent1, charSpacing: 1 }));
    els.push(S('!!track', 'line', { x: sx(0) + cw / 2, y: y0 + ch + 0.55, w: 5 * (cw + gap), h: 0, line: hair(C.text1, 82, 1.25) }));
    for (let k = 0; k < 6; k++) {
      const [n, ic, t, d] = ST_[k], x = sx(k), hl = k === 3;
      els.push(card(n, x, y0, cw, ch, { fill: hl ? tint(C.accent1, 86) : { color: C.background2 }, line: hair(C.accent1, hl ? 20 : 55, hl ? 1.5 : 1), r: 0.08 }));
      els.push(...await iconTile(`${n}-i`, x + 0.2, y0 + 0.2, 0.55, ic, C.accent1));
      els.push(T(`${n}-t`, t, { x: x + 0.2, y: y0 + 0.85, w: cw - 0.3, h: 0.62, fontFace: HEAD, fontSize: 15, color: C.text1, lineSpacingMultiple: 0.9 }));
      els.push(T(`${n}-d`, d, { x: x + 0.2, y: y0 + 1.5, w: cw - 0.32, h: 0.9, fontSize: 11, color: C.text2 }));
      if (k < 5) els.push(arrow(`!!st-a${k}`, x + cw + 0.02, y0 + ch / 2, gap - 0.04, 0, { color: C.accent1 }));
      if (k < 5) els.push(S(`!!dim${k}`, 'roundRect', { x: x - 0.02, y: y0 - 0.02, w: cw + 0.04, h: ch + 0.04, rectRadius: 0.08, fill: { color: C.background1, transparency: 35 }, line: { type: 'none' } }));
      els.push(T(`!!cap${k}`, CAP[k], { x: 0.6, y: y0 + ch + 0.95, w: 12.13, h: 0.5, fontSize: 15, color: C.text1, align: 'center' }));
    }
    els.push(T('!!cap6', CAP[6], { x: 0.6, y: y0 + ch + 0.95, w: 12.13, h: 0.5, fontSize: 15, color: C.text1, align: 'center' }));
    els.push(ST('!!flow', '0x3F9', { shape: pres.shapes.ROUNDED_RECTANGLE, x: sx(0) + cw / 2 - 0.42, y: y0 + ch + 0.39, w: 0.84, h: 0.32, rectRadius: 0.06, fill: { color: C.accent2 }, line: { type: 'none' }, fontFace: MONO, fontSize: 10, bold: true, color: C.background1, align: 'center', valign: 'middle', margin: 0 }));
    // Stage 0 and its caption are static. Shapes whose first effect is an entrance start hidden.
    // Motion paths start from the layout position, so each step of the chip is cumulative.
    const stepF = (cw + gap) / 13.333;
    for (let k = 1; k < 6; k++) {
      const n = ST_[k][0];
      const fx = [
        { type: 'fade', name: `!!dim${k - 1}`, dur: 400, delay: 0 },
        { type: 'fadeout', name: `!!cap${k - 1}`, dur: 250, delay: 0 },
        { type: 'motion', name: '!!flow', path: `M ${((k - 1) * stepF).toFixed(5)} 0 L ${(k * stepF).toFixed(5)} 0 E`, dur: 700, delay: 0 },
        { type: 'wipe', name: `!!st-a${k - 1}`, dir: 'right', dur: 300, delay: 250 },
        ...fades([n, `${n}-i-bg`, `${n}-i-ic`, `${n}-t`, `${n}-d`], 450, 400),
        { type: 'fade', name: `!!cap${k}`, dur: 400, delay: 500 },
      ];
      groups.push({ trigger: 'click', effects: fx });
    }
    groups.push({ trigger: 'click', effects: [
      ...[0, 1, 2, 3, 4].map((k) => ({ type: 'fadeout', name: `!!dim${k}`, dur: 500, delay: 0 })),
      { type: 'fadeout', name: '!!cap5', dur: 250, delay: 0 },
      ...fades(['!!be-box', '!!be-box-t'], 300, 600),
      { type: 'fade', name: '!!cap6', dur: 500, delay: 500 },
    ] });
    add('SOLUTION', els, 'Let me build the architecture the way the data flows through it.\n\nIt starts with the traffic sources: recorded logs in five formats, a live simulator, or a real CAN adapter. [CLICK] The parser turns every format into the same frame stream, and decodes the signals with the DBC file of the vehicle when there is one. [CLICK] For each identifier, we compute 9 features over the last 10 frames. [CLICK] The detection engine scores the frame with the model of its identifier, an Isolation Forest, and completes the score with timing, payload and persistence rules. [CLICK] The REST API, built with FastAPI, serves the results, keeps the sessions in SQLite and writes the explanations. [CLICK] And the WPF client shows everything to the engineer and exports the reports.\n\n[CLICK] Everything in the dashed box runs in one local Python backend; the client talks to it over HTTP. The heart of it is the detection engine: let us zoom in.', { anim: groups });
  }
  {
    // One frame through the frame by frame path (replay, simulation, live). Example scores:
    // a normal frame lands far under the alert threshold, an unusual one far above it.
    const els = [...head(3, 'sol', 'What is the proposed solution?'), sub('How detection works: one frame, from the bus to a decision'), zoomBox()];
    const bw = 1.68, g = 0.31, by = 2.15, bh = 1.6;
    const bx = (k) => 0.85 + k * (bw + g);
    const B = [
      ['CAN frame', 'from the bus or the log'], ['Features', '9 per identifier, window of 10'], ['Isolation Forest', 'the model of this identifier'],
      ['Four layers', 'timing 0.35\npayload 0.35\nmodel 0.20\npersistence 0.10'], ['Fused score', ''], ['Decision', 'alert if the score reaches 0.40'],
    ];
    B.forEach(([t, d], k) => {
      els.push(card(`!!dp${k}`, bx(k), by, bw, bh, { fill: k === 4 ? tint(C.accent1, 88) : tint(C.text1, 95), line: hair(C.accent1, k === 4 ? 30 : 70, 1), r: 0.08 }));
      els.push(T(`!!dp${k}-t`, t, { x: bx(k) + 0.14, y: by + 0.12, w: bw - 0.24, h: 0.36, fontFace: HEAD, fontSize: 14, color: C.text1 }));
      if (d) els.push(T(`!!dp${k}-d`, d, { x: bx(k) + 0.14, y: by + 0.52, w: bw - 0.22, h: 0.95, fontSize: 11, color: C.text2 }));
      if (k < 5) els.push(arrow(`!!dp-a${k}`, bx(k) + bw + 0.03, by + bh / 2, g - 0.06, 0, { color: C.accent1 }));
    });
    // score display inside the fused score box, and the decision chips
    els.push(T('!!sc-ex', 'EXAMPLE', { x: bx(4) + 0.14, y: by + 0.5, w: bw - 0.24, h: 0.22, fontFace: MONO, fontSize: 9, bold: true, color: C.text2, charSpacing: 1 }));
    els.push(T('!!sc-a', '0.17', { x: bx(4) + 0.1, y: by + 0.72, w: bw - 0.2, h: 0.75, fontFace: HEAD, fontSize: 34, color: C.accent4, align: 'center', valign: 'middle' }));
    els.push(T('!!sc-b', '0.82', { x: bx(4) + 0.1, y: by + 0.72, w: bw - 0.2, h: 0.75, fontFace: HEAD, fontSize: 34, color: C.accent3, align: 'center', valign: 'middle' }));
    els.push(ST('!!dec-a', 'NORMAL', { shape: pres.shapes.ROUNDED_RECTANGLE, x: bx(5) + 0.14, y: by + 1.12, w: bw - 0.28, h: 0.36, rectRadius: 0.18, fill: tint(C.accent4, 78), line: hair(C.accent4, 30), fontFace: MONO, fontSize: 11, bold: true, color: C.accent4, align: 'center', valign: 'middle', margin: 0 }));
    els.push(ST('!!dec-b', 'ALERT · HIGH', { shape: pres.shapes.ROUNDED_RECTANGLE, x: bx(5) + 0.14, y: by + 1.12, w: bw - 0.28, h: 0.36, rectRadius: 0.18, fill: tint(C.accent3, 78), line: hair(C.accent3, 30), fontFace: MONO, fontSize: 11, bold: true, color: C.accent3, align: 'center', valign: 'middle', margin: 0 }));
    // the travelling frames, on a track under the pipeline
    const ty = by + bh + 0.45;
    els.push(S('!!dp-track', 'line', { x: bx(0) + bw / 2, y: ty, w: 5 * (bw + g), h: 0, line: hair(C.text1, 82, 1.25) }));
    const fchip = (n, t, color) => ST(n, t, { shape: pres.shapes.ROUNDED_RECTANGLE, x: bx(0) + bw / 2 - 0.62, y: ty - 0.17, w: 1.24, h: 0.34, rectRadius: 0.06, fill: { color }, line: { type: 'none' }, fontFace: MONO, fontSize: 10, bold: true, color: C.background1, align: 'center', valign: 'middle', margin: 0 });
    els.push(fchip('!!fa', 'normal frame', C.accent1), fchip('!!fb', 'unusual frame', C.accent2));
    els.push(card('!!dp-n1', 0.85, ty + 0.45, 5.55, 1.15, { fill: tint(C.text1, 95), line: hair(C.text1, 82) }));
    els.push(T('!!dp-n1-t', [{ text: 'Unscored frames are reported, never hidden. ', options: { bold: true, color: C.text1 } }, { text: 'A frame with no model (warmup, sparse, unmodelled or unseen identifier) is counted as unresolved, with its reason.', options: { color: C.text2 } }], { x: 1.05, y: ty + 0.45, w: 5.2, h: 1.15, fontSize: 12, valign: 'middle' }));
    els.push(card('!!dp-n2', 6.9, ty + 0.45, 5.58, 1.15, { fill: tint(C.text1, 95), line: hair(C.text1, 82) }));
    els.push(T('!!dp-n2-t', [{ text: 'Offline analysis of a whole recording: ', options: { bold: true, color: C.text1 } }, { text: 'same features and models; each frame is flagged when the score of its model passes 0.5.', options: { color: C.text2 } }], { x: 7.1, y: ty + 0.45, w: 5.25, h: 1.15, fontSize: 12, valign: 'middle' }));
    const travel = (n) => ({ type: 'motion', name: n, dx: 5 * (bw + g), dy: 0, dur: 2600, delay: 100 });
    add('SOLUTION', els, 'Here is how one frame is judged, on the path used by replay, simulation and live capture.\n\nA frame arrives. We compute the 9 features of its identifier. The Isolation Forest of that identifier gives a model score. Four layers, timing, payload, the model and persistence, are fused with fixed weights. If the fused score reaches 0.40, an alert is raised.\n\n[CLICK] A normal frame goes through: its score is low, here 0.17, so nothing happens. [CLICK] An unusual frame goes through: its score is high, here 0.82, so an alert is raised, with severity HIGH. These two scores are examples to show the mechanism.\n\nTwo things matter: a frame that no model can judge is reported as unresolved, never counted as normal; and the offline analysis uses the same features and models, with the threshold of each model.', {
      anim: [
        { trigger: 'click', effects: [{ type: 'fade', name: '!!fa', dur: 200, delay: 0 }, travel('!!fa'), { type: 'fade', name: '!!sc-ex', dur: 300, delay: 2000 }, { type: 'pop', name: '!!sc-a', dur: 350, delay: 2000 }, { type: 'pop', name: '!!dec-a', dur: 350, delay: 2500 }, { type: 'fadeout', name: '!!fa', dur: 300, delay: 2800 }] },
        { trigger: 'click', effects: [{ type: 'fadeout', name: '!!sc-a', dur: 250, delay: 0 }, { type: 'fadeout', name: '!!dec-a', dur: 250, delay: 0 }, { type: 'fade', name: '!!fb', dur: 200, delay: 0 }, travel('!!fb'), { type: 'pop', name: '!!sc-b', dur: 350, delay: 2000 }, { type: 'pop', name: '!!dec-b', dur: 350, delay: 2500 }, { type: 'pulse', name: '!!dec-b', scale: 1.15, dur: 300, delay: 2900, repeat: 2 }, { type: 'fadeout', name: '!!fb', dur: 300, delay: 2800 }] },
      ],
    });
  }
  {
    const els = [...head(3, 'sol', 'What is the proposed solution?'), sub('One model per CAN identifier'), zoomBox()];
    const cx = [0.85, 3.9, 6.95, 10.0], cw = 2.55, cy = 2.0, chh = 3.05;
    const titles = ['Frames of one identifier', '9 features', 'Isolation Forest', 'A score from 0 to 1'];
    for (let i = 0; i < 4; i++) {
      els.push(card(`!!mm${i}`, cx[i], cy, cw, chh, { fill: tint(C.text1, 95), line: hair(C.text1, 82) }));
      els.push(T(`!!mm${i}-t`, titles[i], { x: cx[i] + 0.2, y: cy + 0.15, w: cw - 0.3, h: 0.4, fontFace: HEAD, fontSize: 15, color: C.text1 }));
      if (i < 3) els.push(arrow(`!!mm${i}-a`, cx[i] + cw + 0.04, cy + chh / 2, 0.42, 0, { color: C.accent1 }));
    }
    els.push(T('!!mm0-s', 'here 0x3F9, in time order', { x: cx[0] + 0.2, y: cy + 0.55, w: cw - 0.3, h: 0.3, fontSize: 11, color: C.text2 }));
    els.push(T('!!mm0-f', ['35.000  4E 00 00 00', '35.200  4E 00 00 00', '35.400  4E 00 00 00', '35.600  4E 00 00 00', '35.800  4E 00 00 00'].map((l, i, a) => ({ text: l, options: { breakLine: i < a.length - 1, color: C.accent1 } })), { x: cx[0] + 0.2, y: cy + 1.0, w: cw - 0.3, h: 1.6, fontFace: MONO, fontSize: 11.5, lineSpacing: 21 }));
    els.push(T('!!mm1-b', [
      para('TIMING ×3', { fontFace: MONO, bold: true, color: C.accent2, fontSize: 11 }),
      para('time between frames, its rolling mean and std', { color: C.text1, fontSize: 12, paraSpaceAfter: 8 }),
      para('PAYLOAD ×6', { fontFace: MONO, bold: true, color: C.accent6, fontSize: 11 }),
      lastPara('byte change, its rolling mean, std and max; changed bytes; entropy', { color: C.text1, fontSize: 12 }),
    ], { x: cx[1] + 0.2, y: cy + 0.6, w: cw - 0.35, h: 2.0 }));
    els.push(T('!!mm1-w', 'over a window of 10 frames', { x: cx[1] + 0.2, y: cy + 2.62, w: cw - 0.3, h: 0.3, fontSize: 11, color: C.text2 }));
    // isolation sketch
    const bx = cx[2] + 0.35, by = cy + 0.65, bw = 1.85, bh = 1.6;
    els.push(S('!!iso-box', 'rect', { x: bx, y: by, w: bw, h: bh, fill: tint(C.background1, 30), line: hair(C.text1, 70, 1) }));
    const pts = [[0.30, 0.52], [0.40, 0.46], [0.50, 0.50], [0.58, 0.57], [0.36, 0.60], [0.46, 0.58], [0.54, 0.66], [0.28, 0.68], [0.40, 0.70], [0.50, 0.75], [0.60, 0.72], [0.33, 0.80], [0.45, 0.84], [0.56, 0.86]];
    pts.forEach(([px, py], k) => els.push(S(`!!iso-p${k}`, 'ellipse', { x: bx + px * bw - 0.05, y: by + py * bh - 0.05, w: 0.1, h: 0.1, fill: { color: C.text2 }, line: { type: 'none' } })));
    els.push(S('!!iso-v', 'line', { x: bx + 0.78 * bw, y: by, w: 0, h: bh, line: { color: C.accent1, width: 1.25, dashType: 'dash' } }));
    els.push(T('!!iso-v-n', 'cut 1', { x: bx + 0.78 * bw - 0.45, y: by + bh - 0.24, w: 0.4, h: 0.18, fontFace: MONO, fontSize: 8.5, color: C.accent1, align: 'right' }));
    els.push(S('!!iso-h', 'line', { x: bx + 0.78 * bw, y: by + 0.33 * bh, w: 0.22 * bw, h: 0, line: { color: C.accent1, width: 1.25, dashType: 'dash' } }));
    els.push(T('!!iso-h-n', 'cut 2', { x: bx + 0.78 * bw + 0.03, y: by + 0.33 * bh + 0.04, w: 0.38, h: 0.18, fontFace: MONO, fontSize: 8.5, color: C.accent1 }));
    els.push(S('!!iso-odd', 'ellipse', { x: bx + 0.88 * bw - 0.07, y: by + 0.17 * bh - 0.07, w: 0.14, h: 0.14, fill: { color: C.accent3 }, line: { type: 'none' } }));
    const isoT = pts.length * 120;
    const isoAnim = [{ trigger: 'click', effects: [
      ...pts.map((_, k) => ({ type: 'pop', name: `!!iso-p${k}`, dur: 250, delay: k * 120 })),
      { type: 'pop', name: '!!iso-odd', dur: 300, delay: isoT + 250 },
      { type: 'wipe', name: '!!iso-v', dir: 'down', dur: 450, delay: isoT + 800 },
      { type: 'fade', name: '!!iso-v-n', dur: 300, delay: isoT + 1000 },
      { type: 'wipe', name: '!!iso-h', dir: 'right', dur: 350, delay: isoT + 1450 },
      { type: 'fade', name: '!!iso-h-n', dur: 300, delay: isoT + 1600 },
      { type: 'pulse', name: '!!iso-odd', scale: 1.9, dur: 300, delay: isoT + 2000, repeat: 2 },
    ] }];
    els.push(T('!!mm2-c', '200 trees. An unusual frame is isolated in very few cuts.', { x: cx[2] + 0.2, y: cy + 2.35, w: cw - 0.3, h: 0.6, fontSize: 11.5, color: C.text2 }));
    // score scale
    const sx = cx[3] + 0.25, sw = cw - 0.5, sy = cy + 1.15;
    const segc = [C.accent4, C.accent1, C.accent2, C.accent3];
    segc.forEach((c, k) => els.push(S(`!!sc${k}`, 'rect', { x: sx + k * sw / 4, y: sy, w: sw / 4, h: 0.32, fill: { color: c }, line: { type: 'none' } })));
    els.push(S('!!sc-mk', 'line', { x: sx + sw / 2, y: sy - 0.22, w: 0, h: 0.76, line: { color: C.text1, width: 2 } }));
    els.push(T('!!sc-0', '0', { x: sx - 0.1, y: sy + 0.38, w: 0.3, h: 0.25, fontFace: MONO, fontSize: 11, color: C.text2 }));
    els.push(T('!!sc-5', '0.5', { x: sx + sw / 2 - 0.25, y: sy + 0.57, w: 0.5, h: 0.25, fontFace: MONO, fontSize: 11, color: C.text1, align: 'center', bold: true }));
    els.push(T('!!sc-1', '1', { x: sx + sw - 0.15, y: sy + 0.38, w: 0.3, h: 0.25, fontFace: MONO, fontSize: 11, color: C.text2, align: 'right' }));
    els.push(T('!!mm3-c', 'The threshold, 0.5, is set so that 2 % of the training rows pass it. Above it, the frame is flagged.', { x: cx[3] + 0.2, y: cy + 2.0, w: cw - 0.3, h: 0.95, fontSize: 11.5, color: C.text2 }));
    const chips = [['LuDatabase', 'At least 1,000 training rows per identifier, or no model'], ['LuCircleAlert', 'Not scored, and said so: warmup, sparse, unmodelled or unseen identifier'], ['LuClock', 'The timing features carry 64 % of the splits']];
    chips.forEach(([ic, t], k) => {
      const x = 0.85 + k * 3.95;
      els.push(card(`!!mmc${k}`, x, 5.3, 3.8, 1.2, { fill: tint(C.accent1, 90), line: hair(C.accent1, 62) }));
      els.push(IMG(`!!mmc${k}-i`, { data: null, _icon: [ic, C.accent1], x: x + 0.22, y: 5.68, w: 0.42, h: 0.42 }));
      els.push(T(`!!mmc${k}-t`, t, { x: x + 0.8, y: 5.3, w: 2.85, h: 1.2, fontSize: 12.5, color: C.text1, valign: 'middle' }));
    });
    for (const e of els) if (e.k === 'img' && e.o._icon) { e.o.data = await icon(...e.o._icon); delete e.o._icon; }
    add('SOLUTION', els, 'The core idea of the final design is one model per CAN identifier, trained separately for each vehicle.\n\nFor each identifier, we take its frames in time order and compute 9 features over a window of 10 frames: three about timing, the time between frames and its rolling statistics, and six about the payload, how the bytes change and how much information they carry.\n\n[CLICK: the points appear one by one, then the cuts.] An Isolation Forest of 200 trees then scores each frame. Each grey point is a normal frame of this identifier, described by its features; they sit close together. The red point is unusual. A tree cuts the space at random: one cut, a second cut, and the red point is already alone, while a normal point, hidden in the crowd, needs many more cuts. Few cuts means a high anomaly score. The score goes from 0 to 1, and the threshold is set at 0.5 so that 2 percent of the training rows pass it.\n\nAn identifier needs at least 1,000 training rows to get a model. And when a frame cannot be scored, the system says so, with the reason.', { anim: isoAnim });
  }
  {
    // Vehicle-specific models. Real identifiers from the manifests (assets/models/<family>/manifest.json):
    // 0x36 exists on both cars and gets a different model on each.
    const els = [...head(3, 'sol', 'What is the proposed solution?'), sub('Vehicle-specific models: one model per CAN identifier, per vehicle'), zoomBox()];
    const V = [
      { k: 'kia', name: 'KIA EV6', meta: '161 identifier models · 448,198 training frames', ids: ['0x36', '0x37', '0x38', '0x39', '0x4B'], more: '… 161 models in total', x: 0.9 },
      { k: 'jag', name: 'JAGUAR I-PACE', meta: '46 identifier models · 233,598 training frames', ids: ['0x36', '0x41', '0x44', '0x50', '0x63'], more: '… 46 models in total', x: 8.15 },
    ];
    const groups = [];
    for (const v of V) {
      const fx = [];
      els.push(IMG(`!!${v.k}-ic`, { data: await icon('LuCarFront', C.accent1), x: v.x, y: 2.02, w: 0.42, h: 0.42 }));
      els.push(T(`!!${v.k}-n`, v.name, { x: v.x + 0.55, y: 1.98, w: 3.7, h: 0.4, fontFace: MONO, fontSize: 17, bold: true, color: C.text1, charSpacing: 1 }));
      els.push(T(`!!${v.k}-m`, v.meta, { x: v.x, y: 2.45, w: 4.3, h: 0.3, fontSize: 11.5, color: C.text2 }));
      fx.push(...fades([`!!${v.k}-ic`, `!!${v.k}-n`, `!!${v.k}-m`], 0, 400));
      for (let i = 0; i < v.ids.length; i++) {
        const y = 2.95 + i * 0.52;
        els.push(ST(`!!${v.k}${i}-id`, v.ids[i], { shape: pres.shapes.ROUNDED_RECTANGLE, x: v.x, y, w: 1.0, h: 0.4, rectRadius: 0.06, fill: tint(C.accent1, 86), line: hair(C.accent1, 45), fontFace: MONO, fontSize: 13, bold: true, color: C.accent1, align: 'center', valign: 'middle', margin: 0 }));
        els.push(arrow(`!!${v.k}${i}-a`, v.x + 1.06, y + 0.2, 0.5, 0, { color: C.text2 }));
        els.push(ST(`!!${v.k}${i}-m`, 'its own Isolation Forest', { shape: pres.shapes.ROUNDED_RECTANGLE, x: v.x + 1.62, y, w: 2.65, h: 0.4, rectRadius: 0.06, fill: tint(C.text1, 94), line: hair(C.text1, 80), fontSize: 11.5, color: C.text1, align: 'center', valign: 'middle', margin: 0 }));
        fx.push(...fades([`!!${v.k}${i}-id`, `!!${v.k}${i}-a`, `!!${v.k}${i}-m`], 400 + i * 180, 300));
      }
      els.push(T(`!!${v.k}-more`, v.more, { x: v.x, y: 5.6, w: 4.3, h: 0.3, fontFace: MONO, fontSize: 11, color: C.text2 }));
      fx.push({ type: 'fade', name: `!!${v.k}-more`, dur: 300, delay: 1400 });
      groups.push({ trigger: groups.length ? 'click' : 'auto', effects: fx });
    }
    // 0x36 on both cars
    els.push(S('!!kia-hl', 'roundRect', { x: 0.82, y: 2.88, w: 4.53, h: 0.54, rectRadius: 0.08, fill: { color: C.accent2, transparency: 100 }, line: { color: C.accent2, width: 1.5 } }));
    els.push(S('!!jag-hl', 'roundRect', { x: 8.07, y: 2.88, w: 4.53, h: 0.54, rectRadius: 0.08, fill: { color: C.accent2, transparency: 100 }, line: { color: C.accent2, width: 1.5 } }));
    els.push(S('!!hl-link', 'line', { x: 5.37, y: 3.15, w: 2.68, h: 0, line: { color: C.accent2, width: 1.5, dashType: 'dash' } }));
    els.push(card('!!hl-box', 5.55, 3.5, 2.33, 1.95, { fill: tint(C.accent2, 88), line: hair(C.accent2, 45) }));
    els.push(T('!!hl-box-t', [
      { text: '0x36 on both cars', options: { bold: true, color: C.accent2, breakLine: true } },
      { text: 'Kia: 4,871 rows, 9 features', options: { color: C.text1, breakLine: true } },
      { text: 'Jaguar: 3,257 rows, 7 features', options: { color: C.text1, breakLine: true } },
      { text: 'Two different models', options: { color: C.text2 } },
    ], { x: 5.68, y: 3.55, w: 2.1, h: 1.85, fontSize: 11.5, valign: 'middle', paraSpaceAfter: 4 }));
    groups.push({ trigger: 'click', effects: [...fades(['!!kia-hl', '!!jag-hl'], 0, 300), { type: 'wipe', name: '!!hl-link', dir: 'right', dur: 500, delay: 300 }, ...fades(['!!hl-box', '!!hl-box-t'], 700, 400)] });
    els.push(T('!!veh-msg', 'CAN traffic depends on the vehicle, so the models are vehicle specific.', { x: 0.85, y: 6.02, w: 11.63, h: 0.5, fontFace: HEAD, fontSize: 19, color: C.text1, align: 'center', valign: 'middle' }));
    groups.push({ trigger: 'click', effects: [{ type: 'fade', name: '!!veh-msg', dur: 500, delay: 0 }] });
    add('SOLUTION', els, 'Why one model per vehicle? Because CAN traffic depends on the vehicle.\n\nHere is the Kia EV6: 161 identifiers have enough data to get a model, each one its own Isolation Forest. [CLICK] And the Jaguar I-PACE: 46 identifiers, a different set. [CLICK] Even when the same identifier exists on both cars, like 0x36, it does not carry the same traffic: 4,871 training rows and 9 features on the Kia, 3,257 rows and 7 features on the Jaguar, so it gets two different models. [CLICK] CAN traffic depends on the vehicle, so the models are vehicle specific. Making sure the selected vehicle model is really the one used for scoring was in fact one of the defects I found during validation, and the application now shows the status of each model before using it.', { anim: groups });
  }
  {
    const els = [...head(3, 'sol', 'What is the proposed solution?'), sub('From recordings to a model in production'), zoomBox()];
    const top = [['Recordings of one vehicle', ''], ['Split by recording', 'training or holdout, no overlap'], ['9 features', 'per identifier'], ['One forest per identifier', 'at least 1,000 rows'], ['Threshold at 2 %', 'written in a manifest']];
    const tx = (i) => 0.85 + i * 2.37;
    top.forEach(([t, d], i) => {
      els.push(ST(`!!tp${i}`, d ? [{ text: t, options: { fontFace: HEAD, fontSize: 13.5, color: C.text1, breakLine: true } }, { text: d, options: { fontSize: 10.5, color: C.text2 } }] : [{ text: t, options: { fontFace: HEAD, fontSize: 13.5, color: C.text1 } }],
        { shape: pres.shapes.ROUNDED_RECTANGLE, x: tx(i), y: 2.05, w: 2.1, h: 1.05, rectRadius: 0.08, fill: tint(C.text1, 94), line: hair(C.text1, 80), align: 'center', valign: 'middle', margin: [0, 4, 0, 4] }));
      if (i < 4) els.push(arrow(`!!tp${i}-a`, tx(i) + 2.11, 2.575, 0.25, 0, { color: C.accent1 }));
    });
    els.push(arrow('!!tp-down', tx(4) + 1.05, 3.12, 0, 0.6, { color: C.accent1 }));
    els.push(ST('!!tp-hold', [{ text: 'Score the holdout recording', options: { fontFace: HEAD, fontSize: 13.5, color: C.text1 } }], { shape: pres.shapes.ROUNDED_RECTANGLE, x: tx(4), y: 3.75, w: 2.1, h: 1.0, rectRadius: 0.08, fill: tint(C.accent1, 85), line: hair(C.accent1, 30), align: 'center', valign: 'middle', margin: [0, 4, 0, 4] }));
    els.push(arrow('!!tp-hold-a', tx(3) + 2.1, 4.25, 0.23, 0, { color: C.accent1, flipH: true }));
    els.push(ST('!!tp-dec', 'Acceptable?', { shape: pres.shapes.DIAMOND, x: tx(3), y: 3.62, w: 2.1, h: 1.26, fill: tint(C.text1, 92), line: hair(C.text1, 55, 1), fontFace: HEAD, fontSize: 13.5, color: C.text1, align: 'center', valign: 'middle', margin: 0 }));
    els.push(T('!!tp-yes', 'yes', { x: tx(2) + 2.05, y: 3.88, w: 0.6, h: 0.3, fontSize: 11, color: C.accent4, bold: true, align: 'center' }));
    els.push(arrow('!!tp-yes-a', tx(2) + 2.15, 4.25, 0.22, 0, { color: C.accent4, flipH: true }));
    els.push(ST('!!tp-prom', [{ text: 'Promote to production', options: { fontFace: HEAD, fontSize: 13.5, color: C.text1, breakLine: true } }, { text: 'model files in Git LFS', options: { fontSize: 10.5, color: C.text2 } }], { shape: pres.shapes.ROUNDED_RECTANGLE, x: tx(2) - 0.25, y: 3.75, w: 2.4, h: 1.0, rectRadius: 0.08, fill: tint(C.accent4, 84), line: hair(C.accent4, 35), align: 'center', valign: 'middle', margin: [0, 4, 0, 4] }));
    els.push(arrow('!!tp-no-a', tx(3) + 1.05, 4.9, 0, 0.42, { color: C.accent3 }));
    els.push(T('!!tp-no', 'no', { x: tx(3) + 1.12, y: 4.92, w: 0.5, h: 0.3, fontSize: 11, color: C.accent3, bold: true }));
    els.push(ST('!!tp-back', [{ text: 'Hold back', options: { fontFace: HEAD, fontSize: 13.5, color: C.text1, breakLine: true } }, { text: 'MG ZS EV: 43.6 % flagged', options: { fontSize: 10.5, color: C.text2 } }], { shape: pres.shapes.ROUNDED_RECTANGLE, x: tx(3) - 0.15, y: 5.35, w: 2.4, h: 0.95, rectRadius: 0.08, fill: tint(C.accent3, 84), line: hair(C.accent3, 35), align: 'center', valign: 'middle', margin: [0, 4, 0, 4] }));
    const st = [['4', 'vehicles in production'], ['296', 'identifier models'], ['3,436,061', 'training frames'], ['1,130,500', 'holdout frames']];
    st.forEach(([n, l], k) => {
      const x = 0.85 + (k % 2) * 2.05, y = 3.7 + Math.floor(k / 2) * 1.35;
      els.push(T(`!!tps${k}-n`, n, { x, y, w: 2.0, h: 0.6, fontFace: HEAD, fontSize: k < 2 ? 30 : 21, color: C.accent1, valign: 'bottom' }));
      els.push(T(`!!tps${k}-l`, l, { x, y: y + 0.62, w: 2.0, h: 0.32, fontSize: 11.5, color: C.text2 }));
    });
    add('SOLUTION', els, 'A model enters production only through a strict pipeline.\n\nThe recordings of a vehicle are split by recording, not by frame, into training and holdout, and we check that no recording is on both sides. We compute the features, fit one forest per identifier that has at least 1,000 rows, set its threshold at 2 percent, and write all of this in a manifest, so we can always prove how a model was built.\n\nThen we score the holdout recording, which the model has never seen. If the result is acceptable, the model is promoted. If not, it is held back: this is what happened to the MG ZS EV, which flagged 43.6 percent of its holdout.\n\nToday, four vehicles are in production, with 296 identifier models, trained on about 3.4 million frames and evaluated on 1.1 million frames they never saw.');
  }
  {
    // The explanation: alert -> context -> explainer chain -> diagnosis, then the real panel
    // from the application, then the rule of the system: AI explains, the engine decides.
    const els = [...head(3, 'sol', 'What is the proposed solution?'), sub('Explanation: a supporting feature'), zoomBox()];
    const fw = 2.62, fg = 0.38, fy = 2.0, fh = 1.35;
    const fx_ = (k) => 0.85 + k * (fw + fg);
    const F = [
      ['ALERT', 'from the detection engine', C.accent3],
      ['CONTEXT', 'decoded signals, layer scores, temporal pattern, knowledge base', C.text2],
      ['EXPLAINER', '', C.accent6],
      ['DIAGNOSIS', 'dominant signal, likely cause, what to check', C.accent1],
    ];
    F.forEach(([t, d, c], k) => {
      els.push(card(`!!xf${k}`, fx_(k), fy, fw, fh, { fill: tint(hexOf(c) === HX.lt2 ? C.text1 : c, hexOf(c) === HX.lt2 ? 94 : 88), line: hair(c, 35, 1.25), r: 0.08 }));
      els.push(T(`!!xf${k}-t`, t, { x: fx_(k) + 0.18, y: fy + 0.12, w: fw - 0.3, h: 0.3, fontFace: MONO, fontSize: 12.5, bold: true, color: c, charSpacing: 2 }));
      if (d) els.push(T(`!!xf${k}-d`, d, { x: fx_(k) + 0.18, y: fy + 0.48, w: fw - 0.32, h: 0.8, fontSize: 12, color: C.text1 }));
      if (k < 3) els.push(arrow(`!!xf-a${k}`, fx_(k) + fw + 0.04, fy + fh / 2, fg - 0.08, 0, { color: C.text2 }));
    });
    els.push(T('!!xf0-ex', [{ text: '0x063', options: { fontFace: MONO, bold: true, color: C.accent1 } }, { text: '  ·  score 0.535', options: { fontFace: MONO, color: C.text1 } }], { x: fx_(0) + 0.18, y: fy + 0.82, w: fw - 0.3, h: 0.36, fontSize: 12.5 }));
    // explainer chain: Gemini, then Ollama, then rules
    const chain = [['googlegemini.png', 'Gemini'], ['ollama.png', 'Ollama'], [null, 'rules']];
    chain.forEach(([lg, t], k) => {
      const x = fx_(2) + 0.18 + k * 0.82;
      if (lg) els.push(...logoTile(`!!xc${k}`, x, fy + 0.5, 0.42, 0.42, [lg], { pad: 0.05, r: 0.08 }));
      else els.push(S(`!!xc${k}-bg`, 'roundRect', { x, y: fy + 0.5, w: 0.42, h: 0.42, rectRadius: 0.08, fill: tint(C.accent2, 80), line: hair(C.accent2, 40) }));
      els.push(T(`!!xc${k}-t`, t, { x: x - 0.12, y: fy + 0.95, w: 0.66, h: 0.25, fontSize: 9.5, color: C.text2, align: 'center' }));
    });
    els.push(IMG('!!xc2-ic', { data: await icon('LuListChecks', C.accent2), x: fx_(2) + 0.18 + 2 * 0.82 + 0.07, y: fy + 0.57, w: 0.28, h: 0.28 }));
    // the real panel, and the rule
    const shot = fit('f08_explain_crop.png', 0.85, 3.65, 5.6, 2.55);
    els.push(S('!!x-shot-fr', 'rect', { x: shot.x - 0.03, y: shot.y - 0.03, w: shot.w + 0.06, h: shot.h + 0.06, fill: { color: C.background1 }, line: hair(C.accent1, 55, 1) }));
    els.push(IMG('!!x-shot', { path: A('f08_explain_crop.png'), ...shot }));
    els.push(T('!!x-shot-c', 'In the application: the explanation of the alert on 0x063, written by the local model', { x: 0.85, y: shot.y + shot.h + 0.06, w: 5.6, h: 0.26, fontSize: 10.5, color: C.text2 }));
    els.push(T('!!x-r1', 'AI explains.', { x: 6.95, y: 3.6, w: 5.55, h: 0.55, fontFace: HEAD, fontSize: 26, color: C.text1 }));
    els.push(T('!!x-r2', 'The detection engine decides.', { x: 6.95, y: 4.12, w: 5.55, h: 0.55, fontFace: HEAD, fontSize: 26, color: C.accent1 }));
    els.push(T('!!x-r3', [
      { text: 'DETECTION ENGINE  ', options: { fontFace: MONO, bold: true, color: C.accent1, fontSize: 11 } }, { text: 'scores, flags and severities', options: { color: C.text1, breakLine: true } },
      { text: 'EXPLANATION  ', options: { fontFace: MONO, bold: true, color: C.accent6, fontSize: 11 } }, { text: 'words only: it never changes a score, a flag or a severity, and its numbers are checked against the alert', options: { color: C.text2 } },
    ], { x: 6.95, y: 5.0, w: 5.5, h: 1.35, fontSize: 12.5, valign: 'top', paraSpaceAfter: 6 }));
    add('SOLUTION', els, 'The explanation is a supporting feature, separate from detection.\n\nIt always starts from an alert raised by the detection engine, here an alert on identifier 0x063 with a score of 0.535. [CLICK] The backend gathers its context: the decoded signals, the layer scores, the temporal pattern and a small knowledge base. It asks Gemini; if Gemini cannot be reached, a local model through Ollama; and if neither is available, a rule based text, so there is always an answer. The result is a diagnosis in plain language: the dominant signal, the likely cause and what to check.\n\n[CLICK] Here is the real explanation of that alert in the application.\n\n[CLICK] And this is the rule of the system: AI explains, the detection engine decides. The explanation never changes a score, a flag or a severity, and the numbers it writes are checked against the alert.', {
      anim: [
        { trigger: 'click', effects: [
          { type: 'wipe', name: '!!xf-a0', dir: 'right', dur: 300, delay: 0 }, ...fades(['!!xf1', '!!xf1-t', '!!xf1-d'], 250, 400),
          { type: 'wipe', name: '!!xf-a1', dir: 'right', dur: 300, delay: 800 }, ...fades(['!!xf2', '!!xf2-t'], 1050, 400),
          ...fades(['!!xc0-bg', '!!xc0-l0', '!!xc0-t'], 1300, 300), ...fades(['!!xc1-bg', '!!xc1-l0', '!!xc1-t'], 1600, 300), ...fades(['!!xc2-bg', '!!xc2-ic', '!!xc2-t'], 1900, 300),
          { type: 'wipe', name: '!!xf-a2', dir: 'right', dur: 300, delay: 2300 }, ...fades(['!!xf3', '!!xf3-t', '!!xf3-d'], 2550, 400),
        ] },
        { trigger: 'click', effects: fades(['!!x-shot-fr', '!!x-shot', '!!x-shot-c'], 0, 600) },
        { trigger: 'click', effects: [{ type: 'pop', name: '!!x-r1', dur: 400, delay: 0 }, { type: 'pop', name: '!!x-r2', dur: 400, delay: 600 }, { type: 'fade', name: '!!x-r3', dur: 500, delay: 1200 }] },
      ],
    });
  }
  {
    const els = [...head(3, 'sol', 'What is the proposed solution?'), sub('Live capture without a vehicle: the bench rig'), zoomBox()];
    const board = (n, x, t, d) => [card(n, x, 2.05, 2.95, 1.55, { fill: tint(C.text1, 94), line: hair(C.text1, 78) }), ...logoTile(n + '-lg', x + 0.18, 2.22, 0.95, 0.5, ['arduino.png'], { pad: 0.06 }),
      T(n + '-t', t, { x: x + 1.25, y: 2.2, w: 1.6, h: 0.55, fontFace: HEAD, fontSize: 15, color: C.text1, valign: 'middle' }), T(n + '-d', d, { x: x + 0.18, y: 2.85, w: 2.65, h: 0.65, fontSize: 11.5, color: C.text2 })];
    els.push(...board('!!rig-sim', 0.85, 'Simulator', 'Arduino Uno + MCP2515 CAN module'));
    els.push(S('!!rig-bh', 'line', { x: 3.8, y: 2.68, w: 3.0, h: 0, line: { color: C.accent1, width: 3 } }));
    els.push(S('!!rig-bl', 'line', { x: 3.8, y: 2.95, w: 3.0, h: 0, line: { color: C.accent5, width: 3 } }));
    els.push(T('!!rig-bt', 'CAN bus · 500 kbit/s', { x: 3.8, y: 2.2, w: 3.0, h: 0.3, fontSize: 11.5, color: C.text1, align: 'center' }));
    els.push(T('!!rig-bt2', '120 Ω at both ends', { x: 3.8, y: 3.1, w: 3.0, h: 0.3, fontSize: 11, color: C.text2, align: 'center' }));
    els.push(...board('!!rig-br', 6.8, 'Bridge', 'Arduino Uno + MCP2515, speaks slcan over USB'));
    els.push(arrow('!!rig-usb', 9.77, 2.82, 0.5, 0, { color: C.accent1, width: 2 }));
    els.push(T('!!rig-usb-t', 'USB', { x: 9.7, y: 2.45, w: 0.65, h: 0.28, fontFace: MONO, fontSize: 10, bold: true, color: C.text2, align: 'center' }));
    els.push(ST('!!rig-app', [{ text: 'CANvisionNative', options: { fontFace: HEAD, fontSize: 14, color: C.text1, breakLine: true } }, { text: 'python-can → runtime engine', options: { fontSize: 11, color: C.text2 } }], { shape: pres.shapes.ROUNDED_RECTANGLE, x: 10.3, y: 2.05, w: 2.2, h: 1.55, rectRadius: 0.08, fill: tint(C.accent1, 85), line: hair(C.accent1, 30), align: 'center', valign: 'middle', margin: [0, 4, 0, 4] }));
    els.push(T('!!rig-fh', 'WHAT THE SIMULATOR SENDS', { x: 0.85, y: 3.98, w: 6.0, h: 0.3, fontFace: MONO, fontSize: 11, bold: true, color: C.text2, charSpacing: 1 }));
    const fr = [['0x316', 'speed, 60 km/h', 'every 20 ms', C.accent1], ['0x3F9', 'state of charge, 78 %', 'every 200 ms', C.accent1], ['0x666', 'should not exist', 'every 20 s, from 35 s', C.accent2]];
    fr.forEach(([id, m, p, c], k) => {
      const y = 4.38 + k * 0.5;
      els.push(T(`!!rf${k}-id`, id, { x: 0.85, y, w: 0.9, h: 0.4, fontFace: MONO, fontSize: 14, bold: true, color: c, valign: 'middle' }));
      els.push(T(`!!rf${k}-m`, m, { x: 1.85, y, w: 2.6, h: 0.4, fontSize: 13.5, color: C.text1, valign: 'middle' }));
      els.push(T(`!!rf${k}-p`, p, { x: 4.45, y, w: 2.3, h: 0.4, fontSize: 13, color: C.text2, valign: 'middle' }));
    });
    els.push(T('!!rf-rate', 'About 55 frames per second', { x: 0.85, y: 5.95, w: 6.0, h: 0.35, fontSize: 12.5, color: C.text2, italic: true }));
    els.push(card('!!rig-lim', 7.2, 4.0, 5.25, 2.45, { fill: tint(C.accent2, 88), line: hair(C.accent2, 55) }));
    els.push(T('!!rig-lim-t', 'What it shows, and what it does not', { x: 7.45, y: 4.15, w: 4.85, h: 0.4, fontFace: HEAD, fontSize: 15, color: C.accent2 }));
    els.push(T('!!rig-lim-d', [
      para('It tests the transport of live capture, from the bus to the runtime engine.', { color: C.text1, paraSpaceAfter: 8 }),
      lastPara('It does not measure detection: the traffic is synthetic and much simpler than a car\'s. No vehicle was available.', { color: C.text2 }),
    ], { x: 7.45, y: 4.62, w: 4.85, h: 1.7, fontSize: 13 }));
    add('SOLUTION', els, 'No vehicle was available, so I built a bench rig to test live capture. Two Arduino Uno boards, each with an MCP2515 CAN module, are joined by a two wire bus at 500 kilobits per second, with a 120 ohm resistor at each end. The bridge board is connected by USB and speaks the slcan protocol that python-can understands.\n\nThe simulator sends a speed of 60 km/h every 20 milliseconds, a state of charge of 78 percent every 200 milliseconds, and, from the 35th second, a frame on 0x666, an identifier that should not exist.\n\nTo be clear: this tests the transport of live capture, from the bus to the runtime engine. It does not measure detection, because the traffic is synthetic.');
  }

  // ===== 0x500 DEMO =====
  Q(4, 'demo', 'Can we see it working?', 'Can we see it working? Let me show you the platform on a real recording.');
  {
    // The demo slot looks like the application's own window, so the inserted recording and the
    // deck read as one system. Calm on purpose: no animation here.
    const els = [...head(4, 'demo', 'Can we see it working?')];
    // The video fills the whole slide (16:9 like the slide), so it plays full screen. The
    // header stays underneath only so the slide keeps its key and notes.
    els.push({ k: 'media', name: '!!video-rec', o: { type: 'video', path: A('CANvision_demo.mp4'), cover: 'data:image/jpeg;base64,' + fs.readFileSync(A('CANvision_demo_poster.jpg')).toString('base64'), x: 0, y: 0, w: W, h: 7.5 } });
    add('DEMO', els, '[BEFORE THE DEFENSE: insert your screen recording here. Insert > Video > This Device, then drag it over the dark frame, under the CANvision title bar, and resize it to fill the frame. In the Playback tab, set Start to "Automatically" (or "When Clicked On"). Keep the file next to the .pptx or embed it. TIP: record it on the Jaguar I-PACE holdout file canbus_turningon_quickly.csv, the one used in the thesis, so you can truthfully say the model never saw it.]\n\nNow the real application. I import the file, choose the vehicle, replay it, look at the telemetry, open an anomaly and its explanation, and export the report.');
  }

  // ===== 0x600 VALIDATION =====
  Q(5, 'val', 'How do we know it works?', 'How do we know it works? Building the platform was half of the work; the other half was proving that it behaves correctly on real data. The validation took two iterations, with one rule: reproducible evidence before any change, and never tuning a threshold to make the numbers look better.');
  // First iteration, as two slides joined by Morph: the counter, its bar and the six defect rows
  // keep their names, so 15,945 shrinks to 11,971 and each defect turns into a correction.
  const DEFECTS = ['The selected vehicle model was never used for scoring', 'Driving state: 99.93 % "parking" for an hour of driving', 'Diagnostic fields dominated the cause shown to the analyst', 'Replay formats other than CSV bypassed the common parser', 'A polling timer stayed stopped after an import', 'The explanation cache returned another session\'s text'];
  const BARW = 5.3;
  {
    const els = [...head(5, 'val', 'How do we know it works?'), sub('Iteration 2: the first pipeline on a one hour Kia EV6 recording (97,741 frames)', C.accent2)];
    els.push(T('!!v-count', '15,945', { x: 0.6, y: 1.75, w: 5.3, h: 0.95, fontFace: HEAD, fontSize: 56, color: C.accent2 }));
    els.push(T('!!v-lbl', 'alerts, 16.3 % of the frames', { x: 0.6, y: 2.7, w: 5.3, h: 0.38, fontSize: 15, color: C.text1 }));
    els.push(S('!!v-bar', 'rect', { x: 0.6, y: 3.25, w: BARW, h: 0.34, fill: { color: C.accent2 }, line: { type: 'none' } }));
    els.push(T('!!v-why', 'Instead of raising the threshold, we attributed every alert to the layer that dominated it:', { x: 0.6, y: 3.78, w: 5.3, h: 0.55, fontSize: 12.5, color: C.text2 }));
    const parts = [[61.42, C.accent1, 'Machine learning 61.42 %', 'wrong model, wrong driving state'], [31.51, C.accent2, 'Timing 31.51 %', 'irregular UDS polling'], [7.07, C.accent6, 'Payload 7.07 %', 'real sensor variation']];
    let px_ = 0.6;
    const fxA = [];
    parts.forEach(([p, c], k) => { const w = BARW * p / 100; els.push(S(`!!v1-b${k}`, 'rect', { x: px_, y: 4.42, w, h: 0.2, fill: { color: c }, line: { type: 'none' } })); px_ += w; });
    parts.forEach(([p, c, t, d], k) => {
      const y = 4.78 + k * 0.48;
      els.push(S(`!!v1-k${k}`, 'roundRect', { x: 0.6, y: y + 0.08, w: 0.22, h: 0.22, rectRadius: 0.04, fill: { color: c }, line: { type: 'none' } }));
      els.push(T(`!!v1-t${k}`, [{ text: t + '  ', options: { bold: true, color: C.text1 } }, { text: d, options: { color: C.text2 } }], { x: 0.98, y, w: 5.0, h: 0.38, fontSize: 12.5, valign: 'middle' }));
    });
    els.push(T('!!v-fx-h', 'Six silent defects', { x: 6.55, y: 1.8, w: 6.2, h: 0.45, fontFace: HEAD, fontSize: 19, color: C.text1 }));
    const rowsFx = [];
    DEFECTS.forEach((t, k) => {
      const y = 2.42 + k * 0.56;
      els.push(ST(`!!v-f${k}-n`, String(k + 1), { shape: pres.shapes.OVAL, x: 6.55, y: y + 0.04, w: 0.4, h: 0.4, fill: tint(C.accent3, 78), line: hair(C.accent3, 30), fontFace: MONO, fontSize: 12.5, bold: true, color: C.accent3, align: 'center', valign: 'middle', margin: 0 }));
      els.push(T(`!!v-f${k}-t`, t, { x: 7.12, y, w: 5.6, h: 0.48, fontSize: 13.5, color: C.text1, valign: 'middle' }));
      rowsFx.push({ type: 'pop', name: `!!v-f${k}-n`, dur: 300, delay: k * 380 }, { type: 'fade', name: `!!v-f${k}-t`, dur: 350, delay: k * 380 + 80 });
    });
    els.push(T('!!v-note', 'None of them crashed. Each appeared only when the output was compared with a fact known independently, such as the car being driven.', { x: 6.55, y: 5.85, w: 6.18, h: 0.7, fontSize: 12.5, color: C.text2, italic: true }));
    fxA.push({ type: 'pop', name: '!!v-count', dur: 450, delay: 0 }, { type: 'wipe', name: '!!v-bar', dir: 'right', dur: 900, delay: 250 }, { type: 'fade', name: '!!v-lbl', dur: 400, delay: 400 });
    fxA.push({ type: 'fade', name: '!!v-why', dur: 400, delay: 1200 }, ...[0, 1, 2].map((k) => ({ type: 'wipe', name: `!!v1-b${k}`, dir: 'right', dur: 350, delay: 1500 + k * 300 })));
    fxA.push(...[0, 1, 2].flatMap((k) => fades([`!!v1-k${k}`, `!!v1-t${k}`], 1600 + k * 300, 350)));
    add('VALIDATION', els, 'The first iteration tested the first pipeline on a one hour recording of a Kia EV6: 97,741 frames. It produced 15,945 alerts, 16 percent of the frames, which made the system hard to use.\n\nInstead of raising the threshold, we attributed every alert to the layer that dominated it. 61 percent came from the machine learning layer, which pointed to real defects. The timing share came from the irregular diagnostic polling of this recording, and the payload share from real sensor variation, so those two were not defects.\n\n[CLICK] This led to six silent defects. None of them crashed: the selected vehicle model was never used, the car was classified as parked for an hour of driving, and so on. Each one only appeared when I compared the output with a fact I knew independently.', {
      anim: [{ trigger: 'auto', effects: fxA }, { trigger: 'click', effects: [...rowsFx, { type: 'fade', name: '!!v-note', dur: 500, delay: DEFECTS.length * 380 + 300 }] }],
    });
  }
  {
    const els = [...head(5, 'val', 'How do we know it works?'), sub('Iteration 2: six corrections, the same recording, the same threshold', C.accent4)];
    const after = 11971 / 15945;
    els.push(T('!!v-count', '11,971', { x: 0.6, y: 1.75, w: 5.3, h: 0.95, fontFace: HEAD, fontSize: 56, color: C.accent4 }));
    els.push(T('!!v-lbl', 'alerts after the corrections', { x: 0.6, y: 2.7, w: 5.3, h: 0.38, fontSize: 15, color: C.text1 }));
    els.push(S('!!v-bar0', 'rect', { x: 0.6, y: 3.25, w: BARW, h: 0.34, fill: { color: C.accent2, transparency: 100 }, line: { color: C.accent2, width: 1, dashType: 'dash', transparency: 30 } }));
    els.push(S('!!v-bar', 'rect', { x: 0.6, y: 3.25, w: BARW * after, h: 0.34, fill: { color: C.accent4 }, line: { type: 'none' } }));
    els.push(ST('!!v-pct', '−25 %', { shape: pres.shapes.ROUNDED_RECTANGLE, x: 0.6 + BARW * after + 0.12, y: 3.25, w: 0.95, h: 0.34, rectRadius: 0.17, fill: tint(C.accent4, 78), line: { type: 'none' }, fontFace: MONO, fontSize: 11.5, bold: true, color: C.accent4, align: 'center', valign: 'middle', margin: 0 }));
    const BA = [['Saturated model score (≥ 0.999)', '77.6 to 78.6 %', '0.0 %'], ['Replay throughput', '≈ 143 frames/s', '≈ 194.6 frames/s'], ['Driving state', '99.93 % parking', '99.92 % driving']];
    const fxB = [{ type: 'fade', name: '!!v-bar0', dur: 400, delay: 200 }, { type: 'pop', name: '!!v-pct', dur: 350, delay: 900 }];
    BA.forEach(([t, b, a], k) => {
      const y = 3.95 + k * 0.62;
      els.push(T(`!!v-ba${k}-t`, t, { x: 0.6, y, w: 2.2, h: 0.5, fontSize: 12, color: C.text2, valign: 'middle' }));
      els.push(T(`!!v-ba${k}-v`, [{ text: b, options: { color: C.text2 } }, { text: '  →  ', options: { color: C.text2 } }, { text: a, options: { color: C.accent4, bold: true } }], { x: 2.82, y, w: 3.6, h: 0.5, fontSize: 12.5, valign: 'middle' }));
      fxB.push(...fades([`!!v-ba${k}-t`, `!!v-ba${k}-v`], 1200 + k * 250, 400));
    });
    els.push(T('!!v-fx-h', 'Six defects, six corrections', { x: 6.55, y: 1.8, w: 6.2, h: 0.45, fontFace: HEAD, fontSize: 19, color: C.text1 }));
    DEFECTS.forEach((t, k) => {
      const y = 2.42 + k * 0.56;
      els.push(ST(`!!v-f${k}-n`, '✓', { shape: pres.shapes.OVAL, x: 6.55, y: y + 0.04, w: 0.4, h: 0.4, fill: tint(C.accent4, 78), line: hair(C.accent4, 30), fontFace: HEAD, fontSize: 14, bold: true, color: C.accent4, align: 'center', valign: 'middle', margin: 0 }));
      els.push(T(`!!v-f${k}-t`, t, { x: 7.12, y, w: 5.6, h: 0.48, fontSize: 13.5, color: C.text2, valign: 'middle' }));
    });
    els.push(card('!!v-concl', 0.6, 5.88, 12.13, 0.82, { fill: tint(C.accent1, 88), line: hair(C.accent1, 55) }));
    els.push(T('!!v-concl-t', [{ text: 'The threshold was never touched. ', options: { bold: true, color: C.text1 } }, { text: 'The design stayed fragile, so I rebuilt every model with a stricter pipeline in iteration 4.', options: { color: C.text2 } }], { x: 0.85, y: 5.88, w: 11.7, h: 0.82, fontSize: 14, valign: 'middle' }));
    els.push(T('!!v-foot', 'Counts measured after the four data-driven fixes (1 to 4); fixes 5 and 6 were in the client and the explanation cache.', { x: 0.6, y: 6.74, w: 12.13, h: 0.28, fontSize: 10.5, color: C.text2, italic: true }));
    fxB.push(...fades(['!!v-concl', '!!v-concl-t'], 2100, 500), { type: 'fade', name: '!!v-foot', dur: 400, delay: 2400 });
    add('VALIDATION', els, 'Each defect was fixed on its own and verified again with direct evidence. On the same recording, with the same threshold, the alerts went from 15,945 to 11,971, a quarter less. The share of saturated model scores went from 78 percent to zero, replay became faster, from about 143 to about 195 frames per second, and the car is now correctly seen as driving. These counts were measured after the four fixes that change the data path; the last two fixes were in the client and in the explanation cache.\n\nThe threshold was never touched. But the corrected design was still fragile, and I could not always prove which data and settings had produced a model file. So I rebuilt every model with a stricter pipeline: that is the second iteration.', {
      anim: [{ trigger: 'auto', effects: fxB }],
    });
  }
  {
    const els = [...head(5, 'val', 'How do we know it works?'), sub('Iteration 4: the final models on recordings they never saw')];
    const cats = ['Jaguar I-PACE', 'Kia EV6', 'Nissan Leaf 2019', 'ROAD ambient'];
    els.push(card('!!h-chart-bg', 0.6, 1.75, 7.35, 4.85, { r: 0.08 }));
    // Drawn with shapes, not a chart object: a chart embeds an Excel workbook, and PowerPoint refuses
    // to open it on a computer where Excel is missing or WPS handles spreadsheets.
    {
      const vals = [3.09, 2.59, 0.60, 6.09], X0 = 1.35, X1 = 7.55, Y0 = 2.55, Y1 = 5.75, VMAX = 7;
      const yv = (v) => Y1 - (v / VMAX) * (Y1 - Y0), slot = (X1 - X0) / 4, bw = 0.8;
      els.push(T('!!h-title', 'Holdout frames flagged (%)', { x: 0.85, y: 1.92, w: 6.9, h: 0.36, fontSize: 14, color: C.text1, align: 'center' }));
      for (let v = 0; v <= VMAX; v++) {
        els.push(S(`!!h-grid${v}`, 'line', { x: X0, y: yv(v), w: X1 - X0, h: 0, line: { color: '2A3D54', width: 0.75 } }));
        els.push(T(`!!h-ax${v}`, String(v), { x: 0.85, y: yv(v) - 0.12, w: 0.4, h: 0.24, fontSize: 10, color: C.text2, align: 'right' }));
      }
      vals.forEach((v, k) => {
        const cx = X0 + slot * (k + 0.5);
        els.push(S(`!!h-bar${k}`, 'rect', { x: cx - bw / 2, y: yv(v), w: bw, h: Y1 - yv(v), fill: { color: HX.accent1 }, line: { type: 'none' } }));
        els.push(T(`!!h-val${k}`, v.toFixed(2), { x: cx - 0.6, y: yv(v) - 0.32, w: 1.2, h: 0.28, fontSize: 12, color: C.text1, align: 'center' }));
        els.push(T(`!!h-cat${k}`, cats[k], { x: cx - slot / 2, y: Y1 + 0.08, w: slot, h: 0.28, fontSize: 11, color: C.text2, align: 'center' }));
      });
      els.push(S('!!h-target', 'line', { x: X0, y: yv(2), w: X1 - X0, h: 0, line: { color: HX.accent2, width: 2, dashType: 'dash' } }));
      els.push(S('!!h-lg1', 'rect', { x: 2.05, y: 6.2, w: 0.22, h: 0.16, fill: { color: HX.accent1 }, line: { type: 'none' } }));
      els.push(T('!!h-lg1t', 'Holdout frames flagged', { x: 2.35, y: 6.14, w: 2.2, h: 0.28, fontSize: 11, color: C.text2 }));
      els.push(S('!!h-lg2', 'line', { x: 4.6, y: 6.28, w: 0.35, h: 0, line: { color: HX.accent2, width: 2, dashType: 'dash' } }));
      els.push(T('!!h-lg2t', 'Calibration target, 2 %', { x: 5.03, y: 6.14, w: 2.4, h: 0.28, fontSize: 11, color: C.text2 }));
    }
    const call = [
      ['LuLayers', [{ text: '296 identifier models', options: { bold: true, color: C.text1, breakLine: true } }, { text: 'for 4 vehicles', options: { color: C.text2 } }]],
      ['LuDatabase', [{ text: '3,436,061 training frames', options: { bold: true, color: C.text1, breakLine: true } }, { text: '1,130,500 holdout frames, no overlap', options: { color: C.text2 } }]],
      ['LuSearch', [{ text: 'ROAD at 6.09 %: ', options: { bold: true, color: C.text1 } }, { text: 'ID 0x193 never changes in training but changes on the highway. A coverage gap, not a threshold problem.', options: { color: C.text2 } }]],
      ['LuCircleX', [{ text: 'Held back: MG ZS EV, ', options: { bold: true, color: C.text1 } }, { text: '43.6 % flagged, with 78 % of its holdout on identifiers it never saw.', options: { color: C.text2 } }]],
    ];
    const cy = [1.8, 2.75, 3.7, 5.0];
    for (let k = 0; k < 4; k++) {
      els.push(await iconOnly(`!!hc${k}-i`, 8.3, cy[k] + 0.05, 0.42, call[k][0], k === 3 ? C.accent3 : C.accent1));
      els.push(T(`!!hc${k}-t`, call[k][1], { x: 8.9, y: cy[k], w: 3.83, h: k < 2 ? 0.8 : 1.2, fontSize: 13 }));
    }
    els.push(T('!!h-foot', 'No attack labels: a flagged rate on unlabelled recordings is not a false positive rate, a precision or a recall.', { x: 0.6, y: 6.68, w: 12.13, h: 0.32, fontSize: 11.5, color: C.text2, italic: true }));
    add('VALIDATION', els, 'In the second iteration, each final model was scored on a whole recording kept out of its training.\n\nThe rates are close to the 2 percent calibration for the Jaguar and the Kia, below it for the Nissan Leaf, whose holdout comes from the same logger. The ROAD vehicle is at 6 percent, and we could explain why: one identifier, 0x193, never changes in any training recording but does change on the highway recording. It is a coverage gap, not a threshold problem, and we did not tune the threshold on the holdout, because that would make it useless as a test.\n\nThe same protocol showed which model not to trust: the MG ZS EV was held back.\n\nOne honest limit: these recordings have no attack labels, so these are flagged rates, not detection rates.');
  }
  {
    const els = [...head(5, 'val', 'How do we know it works?'), sub('Why Isolation Forest? Compared with LOF and a One Class SVM')];
    const cats = ['Jaguar I-PACE', 'Kia EV6', 'Nissan Leaf 2019', 'ROAD'];
    els.push(card('!!c-chart-bg', 0.6, 1.75, 7.35, 4.85, { r: 0.08 }));
    // Drawn with shapes for the same reason as the holdout chart: no embedded Excel workbook.
    {
      const series = [['Isolation Forest', [3.37, 2.58, 0.48, 6.39], HX.accent1], ['LOF', [13.09, 2.60, 1.47, 3.40], HX.accent5], ['One Class SVM', [13.98, 3.46, 2.04, 6.67], HX.accent6]];
      const X0 = 1.35, X1 = 7.55, Y0 = 2.45, Y1 = 5.75, VMAX = 16, slot = (X1 - X0) / 4, bw = 0.36;
      const yv = (v) => Y1 - (v / VMAX) * (Y1 - Y0);
      els.push(T('!!c-title', 'Holdout rows flagged (%), normal traffic', { x: 0.85, y: 1.92, w: 6.9, h: 0.36, fontSize: 14, color: C.text1, align: 'center' }));
      for (let v = 0; v <= VMAX; v += 2) {
        els.push(S(`!!c-grid${v}`, 'line', { x: X0, y: yv(v), w: X1 - X0, h: 0, line: { color: '2A3D54', width: 0.75 } }));
        els.push(T(`!!c-ax${v}`, String(v), { x: 0.85, y: yv(v) - 0.12, w: 0.4, h: 0.24, fontSize: 10, color: C.text2, align: 'right' }));
      }
      cats.forEach((c, k) => {
        const cx = X0 + slot * (k + 0.5);
        series.forEach(([nm, vals, col], j) => {
          const x = cx + (j - 1) * (bw + 0.04) - bw / 2, v = vals[k];
          els.push(S(`!!c-bar${k}${j}`, 'rect', { x, y: yv(v), w: bw, h: Y1 - yv(v), fill: { color: col }, line: { type: 'none' } }));
          els.push(T(`!!c-val${k}${j}`, v.toFixed(1), { x: x - 0.12, y: yv(v) - 0.24, w: bw + 0.24, h: 0.22, fontSize: 9, color: C.text2, align: 'center' }));
        });
        els.push(T(`!!c-cat${k}`, c, { x: cx - slot / 2, y: Y1 + 0.08, w: slot, h: 0.28, fontSize: 11, color: C.text2, align: 'center' }));
      });
      series.forEach(([nm, , col], j) => {
        els.push(S(`!!c-lg${j}`, 'rect', { x: 1.6 + j * 2.0, y: 6.2, w: 0.22, h: 0.16, fill: { color: col }, line: { type: 'none' } }));
        els.push(T(`!!c-lg${j}t`, nm, { x: 1.9 + j * 2.0, y: 6.14, w: 1.7, h: 0.28, fontSize: 11, color: C.text2 }));
      });
    }
    els.push(T('!!c-mean-h', 'MEAN SHARE FLAGGED', { x: 8.3, y: 1.8, w: 4.4, h: 0.28, fontFace: MONO, fontSize: 11, bold: true, color: C.text2, charSpacing: 1 }));
    [['3.2 %', 'Isolation Forest', C.accent1], ['5.1 %', 'LOF', C.accent5], ['6.5 %', 'One Class SVM', C.accent6]].forEach(([n, l, c], k) => {
      const x = 8.3 + k * 1.5;
      els.push(T(`!!c-m${k}-n`, n, { x, y: 2.12, w: 1.45, h: 0.55, fontFace: HEAD, fontSize: 24, color: c }));
      els.push(T(`!!c-m${k}-l`, l, { x, y: 2.67, w: 1.45, h: 0.3, fontSize: 11, color: C.text2 }));
    });
    els.push(T('!!c-worst', [{ text: 'Lowest worst case: ', options: { bold: true, color: C.text1 } }, { text: '6.4 % for Isolation Forest, against 13.1 % and 14.0 %.', options: { color: C.text2 } }], { x: 8.3, y: 3.2, w: 4.43, h: 0.65, fontSize: 13 }));
    els.push(T('!!c-price', [{ text: 'The price: it is the slowest. ', options: { bold: true, color: C.text1 } }, { text: '23.4 ms to score a frame against 0.97 and 0.42 ms; 138 s of training against 41 and 17 s.', options: { color: C.text2 } }], { x: 8.3, y: 4.0, w: 4.43, h: 0.95, fontSize: 13 }));
    els.push(card('!!c-keep', 8.3, 5.15, 4.43, 1.45, { fill: tint(C.accent1, 88), line: hair(C.accent1, 55) }));
    els.push(T('!!c-keep-t', 'We kept it: the offline analysis, the main use of the platform, needs few and even false alarms more than speed.', { x: 8.5, y: 5.15, w: 4.1, h: 1.45, fontSize: 13, color: C.text1, valign: 'middle' }));
    els.push(T('!!c-foot', 'Same split, same 9 features, same training rows (at most 5,000 per identifier), same threshold rule. No labels.', { x: 0.6, y: 6.68, w: 12.13, h: 0.32, fontSize: 11.5, color: C.text2, italic: true }));
    add('VALIDATION', els, 'Why Isolation Forest? We measured it against the two other candidates, LOF and a One Class SVM, under exactly the same conditions: same split, same features, same training rows, same threshold rule.\n\nSince the holdouts are assumed to be normal traffic, every flagged row is a false alarm. Isolation Forest flags the fewest on average, 3.2 percent against 5.1 and 6.5, and it has the lowest worst case.\n\nThis has a price: it is the slowest of the three, about 23 milliseconds per frame. We kept it because the offline analysis, the main use of the platform, needs few and even false alarms more than it needs speed.');
  }
  {
    const els = [...head(5, 'val', 'How do we know it works?'), sub('Speed, live capture and automated tests')];
    const cols = [
      ['LuGauge', 'Speed', '≈ 24 ms', 'per model call', [['Live path: ', '200 to 260 frames/s'], ['Keeps up with ', 'the Nissan Leaf (about 100 frames/s), not with the Jaguar I-PACE (about 3,000)'], ['Offline: ', '491,969 frames in 187 s']], C.accent1],
      ['LuCable', 'Live capture on the rig', '16,304', 'frames, then one malformed serial line closed the session', [['Fixed: ', 'the bad line is skipped and logged; the link then held at about 55 frames/s'], ['Fixed: ', 'an unplugged rig kept showing old data; the link is now lost after 5 s without frames']], C.accent2],
      ['LuTestTubes', 'Automated tests', '318 + 86', 'backend tests (pytest) and desktop tests (xUnit)', [['Run after every change: ', 'parsers, manifests, model status, scoring, unresolved frames, calibration, PDF report']], C.accent4],
    ];
    for (let k = 0; k < 3; k++) {
      const [ic, t, n, l, body, c] = cols[k];
      const x = 0.6 + k * 4.11, y = 1.8, w = 3.91;
      els.push(card(`!!sp${k}`, x, y, w, 4.85));
      els.push(...await iconTile(`!!sp${k}-i`, x + 0.25, y + 0.25, 0.6, ic, c));
      els.push(T(`!!sp${k}-t`, t, { x: x + 1.0, y: y + 0.25, w: w - 1.2, h: 0.6, fontFace: HEAD, fontSize: 16, color: C.text1, valign: 'middle' }));
      els.push(T(`!!sp${k}-n`, n, { x: x + 0.25, y: y + 1.05, w: w - 0.5, h: 0.7, fontFace: HEAD, fontSize: 34, color: c }));
      els.push(T(`!!sp${k}-l`, l, { x: x + 0.25, y: y + 1.78, w: w - 0.5, h: 0.62, fontSize: 12.5, color: C.text2 }));
      els.push(S(`!!sp${k}-hr`, 'line', { x: x + 0.25, y: y + 2.5, w: w - 0.5, h: 0, line: hair(C.text1, 85, 0.75) }));
      els.push(T(`!!sp${k}-b`, body.map(([a, b], i) => [{ text: a, options: { bold: true, color: C.text1 } }, { text: b, options: { color: C.text2, breakLine: i < body.length - 1 } }]).flat(), { x: x + 0.25, y: y + 2.65, w: w - 0.5, h: 2.05, fontSize: 12.5, paraSpaceAfter: 8 }));
    }
    add('VALIDATION', els, 'Three more results.\n\nSpeed: one model call costs about 24 milliseconds, so the live path processes 200 to 260 frames per second. That keeps up with the Nissan Leaf, about 100 frames per second, but not with buses that carry thousands. The offline analysis is not limited in the same way: almost half a million frames in about three minutes.\n\nLive capture on the bench rig: after 16,304 frames, a single malformed line on the serial link closed the session. Now the bad line is skipped and logged, and the link held at 55 frames per second. I also fixed old data staying on screen after unplugging the rig.\n\nAnd two automated test suites, 318 backend tests and 86 desktop tests, run after every change.');
  }

  // ===== 0x700 LIMITS (calm on purpose: no motion, only a slow reveal) =====
  Q(6, 'lim', 'What are its limits?', 'Before concluding, the limits of this work, stated plainly.');
  {
    const els = [...head(6, 'lim', 'What are its limits?')];
    const L = [
      ['LIVE CAPTURE', 'Tested on a bench rig only, not on a vehicle.', 'The transport of live frames is validated; detection on a live vehicle bus is not measured.'],
      ['LIVE PERFORMANCE', 'About 200 to 260 frames per second.', 'Enough for a slow bus such as the Nissan Leaf (about 100 frames/s), not for buses that carry thousands.'],
      ['HOLDOUT DATA', 'No attack labels.', 'We report flagged rates, not a detection rate, a precision or a recall.'],
      ['VEHICLE COVERAGE', 'Rare identifiers get no model.', 'Jaguar I-PACE: 82.6 % of the holdout frames scored. One model held back (MG ZS EV).'],
    ];
    const fx = [];
    L.forEach(([lab, s1, s2], k) => {
      const y = 1.6 + k * 1.2;
      els.push(ST(`!!lm${k}-l`, lab, { shape: pres.shapes.ROUNDED_RECTANGLE, x: 0.6, y: y + 0.18, w: 3.3, h: 0.62, rectRadius: 0.08, fill: tint(C.accent2, 90), line: hair(C.accent2, 50), fontFace: MONO, fontSize: 13, bold: true, color: C.accent2, align: 'center', valign: 'middle', margin: 0, charSpacing: 1 }));
      els.push(arrow(`!!lm${k}-a`, 4.02, y + 0.49, 0.55, 0, { color: C.text2 }));
      els.push(T(`!!lm${k}-t`, [{ text: s1, options: { bold: true, color: C.text1, breakLine: true } }, { text: s2, options: { color: C.text2, fontSize: 13 } }], { x: 4.75, y, w: 7.98, h: 0.98, fontSize: 17, valign: 'middle' }));
      fx.push(...fades([`!!lm${k}-l`, `!!lm${k}-a`, `!!lm${k}-t`], k * 450, 700));
    });
    els.push(T('!!lm-foot', 'Each limit is measured and stated in the report.', { x: 0.6, y: 6.5, w: 12.13, h: 0.3, fontSize: 12, color: C.text2, italic: true, align: 'center' }));
    fx.push({ type: 'fade', name: '!!lm-foot', dur: 700, delay: 2000 });
    add('LIMITS', els, 'Four limits, which the report states clearly.\n\nLive capture was tested on a bench rig, not on a vehicle: we know the frames travel correctly from the bus to the engine, but we did not measure detection on a live car.\n\nThe live path scores about 200 to 260 frames per second: enough for a slow bus like the Nissan Leaf, not for buses that carry thousands of frames per second.\n\nThe holdout recordings carry no attack labels, so we report flagged rates, and never a detection rate, a precision or a recall.\n\nAnd some identifiers are too rare to get a model: on the Jaguar I-PACE, 82.6 percent of the holdout frames could be scored. One model, the MG ZS EV, was held back because it failed its evaluation.', { anim: [{ trigger: 'auto', effects: fx }] });
  }

  // ===== 0x800 CONCLUSION =====
  Q(7, 'conc', 'What can we conclude?', 'What can we conclude?');
  {
    const els = [...head(7, 'conc', 'What can we conclude?')];
    els.push(card('!!cc-d', 0.6, 1.55, 7.15, 4.45));
    els.push(T('!!cc-d-h', 'DELIVERED', { x: 0.9, y: 1.75, w: 6.6, h: 0.3, fontFace: MONO, fontSize: 12, bold: true, color: C.accent4, charSpacing: 2 }));
    const D = ['A Windows client and a Python backend: recorded logs, a live simulator and live capture', '4 vehicle models, 296 identifier models, evaluated on 1,130,500 frames they never saw', 'A training pipeline that refuses a model failing its evaluation', 'Explanations in plain language, kept apart from detection', 'A bench rig with its firmware, and 318 + 86 automated tests'];
    const fx = [];
    for (let k = 0; k < D.length; k++) {
      const y = 2.2 + k * 0.74;
      els.push(await iconOnly(`!!cc-d${k}-i`, 0.9, y + 0.08, 0.36, 'LuCircleCheck', C.accent4));
      els.push(T(`!!cc-d${k}-t`, D[k], { x: 1.45, y, w: 6.1, h: 0.55, fontSize: 13.5, color: C.text1, valign: 'middle' }));
      fx.push(...fades([`!!cc-d${k}-i`, `!!cc-d${k}-t`], k * 250, 400));
    }
    els.push(card('!!cc-l', 7.95, 1.55, 4.78, 4.45, { fill: tint(C.accent1, 90), line: hair(C.accent1, 60) }));
    els.push(T('!!cc-l-h', 'WHAT I LEARNED', { x: 8.25, y: 1.75, w: 4.3, h: 0.3, fontFace: MONO, fontSize: 12, bold: true, color: C.accent1, charSpacing: 2 }));
    const Ls = ['The most costly defects were the silent ones: none of them crashed.', 'A holdout is only meaningful when the split is made by recording, not by frame.', 'A flagged rate on unlabelled data is not a detection rate.'];
    for (let k = 0; k < Ls.length; k++) {
      const y = 2.2 + k * 0.95;
      els.push(await iconOnly(`!!cc-l${k}-i`, 8.25, y + 0.1, 0.34, 'LuLightbulb', C.accent1));
      els.push(T(`!!cc-l${k}-t`, Ls[k], { x: 8.75, y, w: 3.85, h: 0.8, fontSize: 13.5, color: C.text1, valign: 'middle' }));
      fx.push(...fades([`!!cc-l${k}-i`, `!!cc-l${k}-t`], 1400 + k * 250, 400));
    }
    els.push(T('!!cc-q', '"A detection system is only as trustworthy as the evidence behind each of its numbers."', { x: 0.6, y: 6.2, w: 12.13, h: 0.55, fontFace: HEAD, fontSize: 17, italic: true, color: C.text1, align: 'center', valign: 'middle' }));
    fx.push({ type: 'fade', name: '!!cc-q', dur: 700, delay: 2400 });
    add('CONCLUSION', els, 'To conclude. The project delivered a Windows client and a Python backend that handle recorded logs, a live simulator and live capture; four vehicle models evaluated on more than a million frames they never saw; a training pipeline that refuses a model failing its evaluation; explanations in plain language, kept apart from detection; a bench rig; and two test suites.\n\nWhat I learned: the most costly defects were the silent ones; a holdout is only meaningful when you split by recording; and a flagged rate on unlabelled data is not a detection rate. In one sentence: a detection system is only as trustworthy as the evidence behind each of its numbers.', { anim: [{ trigger: 'auto', effects: fx }] });
  }
  {
    const els = [...head(7, 'persp', 'What are the perspectives?')];
    const P = [['Live capture on a real vehicle', 'The first step: it closes milestone M2.'], ['Labelled attacks', 'Evaluate the final models on recordings with labelled attacks, such as the ROAD dataset, to measure what they detect as well as what they flag.'], ['A faster live path', 'Score several frames at once or use fewer trees, with each change measured on the holdout recordings.'], ['More recordings per vehicle', 'A holdout for every vehicle, and a model for more of the rare identifiers.']];
    const fx = [];
    for (let k = 0; k < 4; k++) {
      const x = k % 2 ? 6.75 : 0.6, y = k < 2 ? 1.55 : 4.1, w = 5.98, h = 2.3;
      els.push(card(`!!pp${k}`, x, y, w, h));
      els.push(T(`!!pp${k}-n`, `0${k + 1}`, { x: x + 0.3, y: y + 0.25, w: 0.9, h: 0.6, fontFace: MONO, fontSize: 28, bold: true, color: C.accent1 }));
      els.push(T(`!!pp${k}-t`, P[k][0], { x: x + 1.3, y: y + 0.3, w: w - 1.55, h: 0.5, fontFace: HEAD, fontSize: 18, color: C.text1, valign: 'middle' }));
      els.push(T(`!!pp${k}-d`, P[k][1], { x: x + 1.3, y: y + 0.9, w: w - 1.55, h: 1.25, fontSize: 13.5, color: C.text2 }));
      fx.push(...fades([`!!pp${k}`, `!!pp${k}-n`, `!!pp${k}-t`, `!!pp${k}-d`], k * 300, 450));
    }
    add('CONCLUSION', els, 'And what comes next? First, validate live capture on a real vehicle, which would close milestone M2. Second, evaluate the final models on recordings with labelled attacks, such as the ROAD dataset, to measure what they detect and not only what they flag. Third, make the live path fast enough for busy buses, by scoring several frames at once or using fewer trees, measuring each change on the holdouts. And fourth, collect more recordings per vehicle, to give every vehicle a holdout and more rare identifiers a model.', { anim: [{ trigger: 'auto', effects: fx }] });
  }
  {
    // Final sequence: the name, five verbs, one sentence; then thanks on a click.
    const words = ['DIAGNOSE', 'MONITOR', 'DETECT', 'EXPLAIN', 'VALIDATE'];
    const ww = 1.9, wg = 0.25, wx0 = (W - (5 * ww + 4 * wg)) / 2;
    const els = [T('!!title', [{ text: 'CANvision', options: { color: C.text1 } }, { text: 'Native', options: { color: C.accent1 } }], { x: 1.2, y: 1.85, w: 10.93, h: 1.05, fontFace: HEAD, fontSize: 56, align: 'center' })];
    const fx = [{ type: 'fade', name: '!!title', dur: 800, delay: 0 }];
    words.forEach((t, k) => {
      els.push(T(`!!fw${k}`, t, { x: wx0 + k * (ww + wg), y: 3.2, w: ww, h: 0.4, fontFace: MONO, fontSize: 15, bold: true, color: C.accent1, align: 'center', charSpacing: 3 }));
      if (k < 4) els.push(S(`!!fw${k}-s`, 'ellipse', { x: wx0 + k * (ww + wg) + ww + wg / 2 - 0.035, y: 3.37, w: 0.07, h: 0.07, fill: { color: C.text2 }, line: { type: 'none' } }));
      fx.push({ type: 'fade', name: `!!fw${k}`, dur: 450, delay: 900 + k * 420 });
      if (k < 4) fx.push({ type: 'fade', name: `!!fw${k}-s`, dur: 300, delay: 1100 + k * 420 });
    });
    els.push(T('!!tagline', 'From CAN frames to explainable diagnostics.', { x: 1.2, y: 3.95, w: 10.93, h: 0.6, fontFace: HEAD, fontSize: 24, color: C.text1, align: 'center' }));
    fx.push({ type: 'fade', name: '!!tagline', dur: 900, delay: 3200 });
    const esp = fit('esprit_white.png', 4.6, 6.15, 1.9, 0.6, 'right');
    const cap = fit('capgemini_white.png', 6.85, 6.28, 2.2, 0.36, 'left');
    els.push(T('!!thx', [{ text: 'Thank you for your attention.  ', options: { color: C.text2 } }, { text: 'Questions?', options: { color: C.accent1, bold: true } }], { x: 1.2, y: 5.0, w: 10.93, h: 0.5, fontSize: 20, align: 'center' }));
    els.push(IMG('!!logo-esprit', { path: A('esprit_white.png'), ...esp }), S('!!logo-sep', 'line', { x: 6.67, y: 6.2, w: 0, h: 0.48, line: hair(C.text2, 40, 1) }), IMG('!!logo-capg', { path: A('capgemini_white.png'), ...cap }));
    add('CONCLUSION', els, 'CANvisionNative: a platform to diagnose, monitor, detect, explain and validate. From CAN frames to explainable diagnostics.\n\n[CLICK] Thank you for your attention. I am ready for your questions.', {
      layout: 'CV_PLAIN',
      anim: [{ trigger: 'auto', effects: fx }, { trigger: 'click', effects: [{ type: 'fade', name: '!!thx', dur: 700, delay: 0 }, ...fades(['!!logo-esprit', '!!logo-sep', '!!logo-capg'], 300, 700)] }],
    });
  }

  // ---------- talk length: slide keys, dropped slides, hidden backup, short notes ----------
  // The deck must fit 20 minutes with a 5 minute demo. Slides get a stable key; DROP removes
  // slides, BACKUP moves slides after the final one as hidden slides (shown only on demand),
  // and notes.js holds the short speaker notes of the presented slides.
  const NOTES = require('./notes.js');
  const DROP = new Set(['Q:who', 'who#1', 'Q:nfr', 'Q:method']);
  const BACKUP = { 'nfr#1': 'Non functional requirements', 'sol#5': 'Training and promotion pipeline', 'sol#7': 'Bench rig', 'val#4': 'Isolation Forest compared with LOF and One Class SVM', 'val#5': 'Speed, live capture and tests' };
  {
    const occ = {};
    for (const sd of slides) {
      const q = sd.els.find((e) => e.name.startsWith('!!q-'));
      if (sd.isQ) { sd.key = 'Q:' + q.name.slice(4); continue; }
      const base = q ? q.name.slice(4) : sd.els.find((e) => !/^!!(tag|prog)-/.test(e.name)).name.slice(2);
      occ[base] = (occ[base] || 0) + 1;
      sd.key = `${base}#${occ[base]}`;
    }
  }
  for (let i = slides.length - 1; i >= 0; i--) if (DROP.has(slides[i].key)) slides.splice(i, 1);
  {
    const main = slides.filter((sd) => !BACKUP[sd.key]), back = slides.filter((sd) => BACKUP[sd.key]);
    back.forEach((sd) => { sd.sec = 'BACKUP'; sd.hidden = true; });
    slides.length = 0;
    slides.push(...main, ...back);
    for (const sd of slides) if (NOTES[sd.key]) sd.notes = NOTES[sd.key];
    const fin = slides.find((sd) => sd.key === 'title#1');
    fin.notes += '\n\nBACKUP, hidden slides for questions (in the slideshow, type the number and press Enter): ' + back.map((sd) => `${slides.indexOf(sd) + 1} ${BACKUP[sd.key]}`).join('; ') + '.';
    console.log(slides.map((sd, i) => `${i + 1}:${sd.key}${sd.hidden ? '(hidden)' : ''}`).join('  '));
  }

  // ---------- morph ghosts: questions slide in from the right, old headers slide out to the left ----------
  const mov = (n) => n.startsWith('!!q-') || n.startsWith('!!tag-');
  const shift = (e, dx) => { const c = structuredClone(e); c.o.x += dx; return c; };
  for (let i = 1; i < slides.length; i++) {
    const prev = slides[i - 1], cur = slides[i];
    if (!cur.isQ) continue;
    const pn = new Set(prev.els.map((e) => e.name)), cn = new Set(cur.els.map((e) => e.name));
    for (const e of prev.els.slice()) if (mov(e.name) && !cn.has(e.name)) cur.els.push(shift(e, -14));
    for (const e of cur.els.slice()) if (mov(e.name) && !pn.has(e.name)) prev.els.push(shift(e, 14));
  }

  // ---------- render ----------
  pres.defineSlideMaster({ title: 'CV_DARK', background: { color: HX.dk1 }, slideNumber: { x: 12.23, y: 7.02, w: 0.5, h: 0.26, fontFace: 'Segoe UI', fontSize: 10, color: HX.lt2, align: 'right' } });
  pres.defineSlideMaster({ title: 'CV_PLAIN', background: { color: HX.dk1 } });
  const SH = SHAPES();
  let curSec = null;
  const secStart = SECS.map((sec) => slides.findIndex((sd) => sd.sec === sec.label) + 1);
  slides.forEach((sd, si) => {
    const secTitle = sd.sec[0] + sd.sec.slice(1).toLowerCase();
    if (secTitle !== curSec) { pres.addSection({ title: secTitle }); curSec = secTitle; }
    const slide = pres.addSlide({ masterName: sd.layout, sectionTitle: secTitle });
    const seen = new Set();
    const gone = new Set();  // PRINT=1: elements whose last effect is an exit are not in the final state
    if (process.env.PRINT && sd.anim) { const last = {}; sd.anim.forEach((g) => g.effects.forEach((e) => { last[e.name] = e.type; })); for (const [n, t] of Object.entries(last)) if (t === 'fadeout') gone.add(n); }
    sd.els.forEach((e, ei) => {
      let name = e.name || `u${si}-${ei}`;
      if (seen.has(name)) throw new Error(`duplicate name ${name} on slide ${si + 1}`);
      if (gone.has(name)) return;
      seen.add(name);
      const o = structuredClone(e.o);
      o.objectName = name;
      // Section links. On a shape with text, PowerPoint would also style the text as a link
      // (underlined), so the link goes on an invisible shape laid over the element instead.
      let link = null;
      if (o._link !== undefined) { if (secStart[o._link] > 0) link = { slide: secStart[o._link], tooltip: SECS[o._link].label }; delete o._link; }
      if (link && e.k === 'shape') { o.hyperlink = link; link = null; }
      const linkOver = () => { if (link) slide.addShape(SH.rect, { x: o.x, y: o.y, w: o.w, h: o.h, fill: { color: C.background1, transparency: 100 }, line: { type: 'none' }, hyperlink: link, objectName: name + '-link' }); };
      const txt = (t) => JSON.parse(JSON.stringify(t).replace(/\{\{sec:(\d)\}\}/g, (m0, k) => String(secStart[+k]).padStart(2, '0')));
      if (e.k === 'text') { slide.addText(txt(e.text), { isTextBox: true, margin: 0, valign: 'top', ...o }); linkOver(); return; }
      if (e.k === 'stext') { slide.addText(structuredClone(e.text), o); linkOver(); return; }
      else if (e.k === 'stext') slide.addText(structuredClone(e.text), o);
      else if (e.k === 'shape') slide.addShape(SH[e.shape], o);
      else if (e.k === 'img') { if (o.data === null) throw new Error('icon not resolved ' + name); slide.addImage(o); }
      else if (e.k === 'media') { delete o.objectName; slide.addMedia(o); }
      else if (e.k === 'chart') { if (Array.isArray(e.type)) slide.addChart(structuredClone(e.type), o); else slide.addChart(e.type, structuredClone(e.data), o); }
    });
    if (sd.notes) slide.addNotes(sd.notes);
  });
  // animation spec for post.py, keyed by slide number; names are the shapes' objectName
  const animSpec = {};
  slides.forEach((sd, i) => { if (sd.anim) animSpec[i + 1] = sd.anim; });
  for (const [n, groups] of Object.entries(animSpec)) for (const g of groups) for (const e of g.effects)
    if (!slides[n - 1].els.some((el) => el.name === e.name)) throw new Error(`animation target ${e.name} missing on slide ${n}`);
  animSpec._hidden = slides.map((sd, i) => (sd.hidden ? i + 1 : 0)).filter(Boolean);
  fs.writeFileSync(path.join(__dirname, 'anim.json'), JSON.stringify(animSpec, null, 1));
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log('wrote', OUT, slides.length, 'slides');
}

build().catch((e) => { console.error(e); process.exit(1); });
