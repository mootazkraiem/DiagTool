// Light version of the defense deck: white background, one accent colour, plain layouts, and no
// motion other than a fade between slides and simple fades on click, at the [CLICK] marks of the
// speech. The same slides as the dark deck (build.js), in the same order, with the same notes, so
// speech.md fits both decks slide for slide.
//
//   node build_light.js <out.pptx>      writes the deck and light_anim.json
//   powershell -File light_anim.ps1 ... adds the transitions and the click fades with PowerPoint
//                                        itself, so WPS and PowerPoint play them the same way
const fs = require('fs');
const path = require('path');
const pptxgen = require('pptxgenjs');
const sharp = require('sharp');
const NOTES = require('./notes.js');

const OUT = process.argv[2] || path.join(__dirname, 'light.pptx');
const A = (f) => path.join(__dirname, 'assets', f);
const FONT = 'Segoe UI', HEAD = 'Segoe UI Semibold', MONO = 'Consolas';
const K = {
  ink: '1F2933', body: '3E4C59', mute: '7B8794', rule: 'D9DEE4', panel: 'F4F6F8',
  acc: '0F766E', accSoft: 'E3F2F0', warn: 'B45309', warnSoft: 'FCF1E3', red: 'B42318', redSoft: 'FDECEB',
  green: '15803D', greenSoft: 'E8F5EC', blue: '2563EB', blueSoft: 'E8EFFD',
};
const SEC = ['Context', 'Problem', 'Objectives and requirements', 'Proposed solution', 'Demonstration', 'Validation', 'Limits', 'Conclusion'];

const pres = new pptxgen();
pres.layout = 'LAYOUT_WIDE';
pres.author = 'Mohamed Mootaz Ben Kraiem';
pres.title = 'CANvisionNative';
pres.theme = { headFontFace: HEAD, bodyFontFace: FONT };
pres.defineSlideMaster({
  title: 'LIGHT', background: { color: 'FFFFFF' },
  objects: [{ text: { text: 'CANvisionNative', options: { x: 0.6, y: 7.0, w: 4, h: 0.3, fontFace: FONT, fontSize: 10, color: K.mute, margin: 0 } } }],
  slideNumber: { x: 12.23, y: 7.0, w: 0.5, h: 0.3, fontFace: FONT, fontSize: 10, color: K.mute, align: 'right' },
});
pres.defineSlideMaster({ title: 'PLAIN', background: { color: 'FFFFFF' } });

// ---------- slide helpers ----------
const deck = [];
let cur = null, curSec = null;
function slide(sec, title, notes, o = {}) {
  const secTitle = o.hidden ? 'Backup' : (sec === null ? 'Opening' : SEC[sec]);
  if (secTitle !== curSec) { pres.addSection({ title: secTitle }); curSec = secTitle; }
  const s = pres.addSlide({ masterName: o.plain ? 'PLAIN' : 'LIGHT', sectionTitle: secTitle });
  cur = { s, title: o.label || title, notes, clicks: [], names: new Set(), hidden: !!o.hidden };
  deck.push(cur);
  if (title) {
    text('sec', o.hidden ? 'Backup' : `${sec + 1}   ${SEC[sec]}`, { x: 0.6, y: 0.4, w: 9, h: 0.3, fontSize: 13, bold: true, color: K.acc });
    text('title', title, { x: 0.6, y: 0.68, w: 12.13, h: 0.72, fontFace: HEAD, fontSize: 28, color: K.ink });
  }
}
function nm(name) {
  if (cur.names.has(name)) throw new Error(`duplicate ${name} on slide ${deck.length}`);
  cur.names.add(name);
  return name;
}
function onClick(name, c) { if (c) (cur.clicks[c - 1] = cur.clicks[c - 1] || []).push(name); }
function text(name, t, o, c) {
  cur.s.addText(t, { fontFace: FONT, fontSize: 16, color: K.body, margin: 0, valign: 'top', ...o, objectName: nm(name) });
  onClick(name, c);
}
function box(name, t, o, c) {
  cur.s.addText(t, {
    shape: pres.shapes.ROUNDED_RECTANGLE, rectRadius: 0.05, fontFace: FONT, fontSize: 14, color: K.ink, align: 'center', valign: 'middle',
    margin: 6, fill: { color: K.panel }, line: { color: K.rule, width: 1 }, ...o, objectName: nm(name),
  });
  onClick(name, c);
}
function rect(name, o, c) {
  cur.s.addShape(o.round === false ? pres.shapes.RECTANGLE : pres.shapes.ROUNDED_RECTANGLE, { rectRadius: 0.05, fill: { color: K.panel }, line: { color: K.rule, width: 1 }, ...o, objectName: nm(name) });
  onClick(name, c);
}
function dot(name, x, y, d, color, c) {
  cur.s.addShape(pres.shapes.OVAL, { x: x - d / 2, y: y - d / 2, w: d, h: d, fill: { color }, line: { type: 'none' }, objectName: nm(name) });
  onClick(name, c);
}
function line(name, x, y, w, h, o = {}, c) {
  cur.s.addShape(pres.shapes.LINE, { x, y, w, h, flipH: o.flipH, flipV: o.flipV, line: { color: o.color || K.rule, width: o.width || 1, dashType: o.dash, endArrowType: o.arrow ? 'triangle' : undefined }, objectName: nm(name) });
  onClick(name, c);
}
const arrow = (name, x, y, w, h, o = {}, c) => line(name, x, y, w, h, { color: K.mute, width: 1.5, arrow: true, ...o }, c);
function image(name, o, c) { cur.s.addImage({ ...o, objectName: nm(name) }); onClick(name, c); }
const run = (t, o = {}) => ({ text: t, options: o });
const br = (t, o = {}) => ({ text: t, options: { ...o, breakLine: true } });
// a title in bold followed by a line of explanation, as one text box
const titled = (t, d, o = {}) => [br(t, { bold: true, color: o.tc || K.ink, fontSize: o.ts }), run(d, { color: o.dc || K.body, fontSize: o.ds })];

const dims = {};
async function fit(f, x, y, w, h, align = 'center') {
  if (!dims[f]) { const m = await sharp(A(f)).metadata(); dims[f] = [m.width, m.height]; }
  const [iw, ih] = dims[f], r = Math.min(w / iw, h / ih), fw = iw * r, fh = ih * r;
  return { x: align === 'left' ? x : align === 'right' ? x + w - fw : x + (w - fw) / 2, y: y + (h - fh) / 2, w: fw, h: fh };
}
// Section opener, like the question slides of the dark deck: the part and its question, centred.
function question(sec, q, key) {
  slide(sec, null, NOTES[key], { label: q });
  text('q-sec', `Part ${sec + 1} of 8:  ${SEC[sec]}`, { x: 1.2, y: 2.3, w: 10.93, h: 0.35, fontSize: 15, bold: true, color: K.acc, align: 'center' });
  text('q', q, { x: 1.2, y: 2.8, w: 10.93, h: 1.7, fontFace: HEAD, fontSize: 40, color: K.ink, align: 'center' });
  const x0 = (13.333 - (8 * 0.5 + 7 * 0.1)) / 2;
  for (let i = 0; i < 8; i++) {
    rect(`q-p${i}`, { x: x0 + i * 0.6, y: 4.9, w: 0.5, h: 0.08, round: false, fill: { color: i === sec ? K.acc : i < sec ? '9FD3CC' : 'E3E7EB' }, line: { type: 'none' } });
  }
}

async function build() {
  // 1. Title
  slide(null, null, NOTES['h-base#1'], { plain: true, label: 'Title' });
  image('logo-esprit', { path: A('esprit.png'), ...await fit('esprit.png', 8.9, 0.45, 1.8, 0.62, 'right') });
  line('logo-sep', 10.95, 0.5, 0, 0.52, { color: K.rule });
  image('logo-capg', { path: A('capgemini.png'), ...await fit('capgemini.png', 11.15, 0.55, 1.6, 0.42, 'left') });
  text('kicker', 'Graduation project in Information Technology, 2025/2026', { x: 0.6, y: 0.62, w: 7.5, h: 0.32, fontSize: 14, color: K.mute });
  text('name', [run('CANvision', { color: K.ink }), run('Native', { color: K.acc })], { x: 0.6, y: 1.7, w: 7.2, h: 1.0, fontFace: HEAD, fontSize: 54 });
  rect('name-bar', { x: 0.62, y: 2.8, w: 0.9, h: 0.07, round: false, fill: { color: K.acc }, line: { type: 'none' } });
  text('subtitle', 'A diagnostic and validation platform for the CAN traffic of Battery Management Systems', { x: 0.6, y: 3.05, w: 6.6, h: 0.95, fontSize: 21, color: K.body });
  text('author', [br('Presented by', { color: K.mute, fontSize: 13 }), run('Mohamed Mootaz Ben Kraiem', { color: K.ink, fontSize: 22, fontFace: HEAD })], { x: 0.6, y: 4.45, w: 6.6, h: 0.8 });
  text('sup0', [br('Academic supervisor', { color: K.mute, fontSize: 12 }), br('Mrs Nadia Boulifa', { color: K.ink, fontSize: 16, fontFace: HEAD }), run('ESPRIT', { color: K.body, fontSize: 13 })], { x: 0.6, y: 5.55, w: 3.2, h: 0.95 });
  text('sup1', [br('Corporate supervisor', { color: K.mute, fontSize: 12 }), br('Mr Hamda Guizani', { color: K.ink, fontSize: 16, fontFace: HEAD }), run('Capgemini Engineering', { color: K.body, fontSize: 13 })], { x: 3.9, y: 5.55, w: 3.4, h: 0.95 });
  {
    const shot = await fit('f02_dashboard.png', 7.75, 1.75, 5.0, 4.6);
    rect('shot-frame', { x: shot.x - 0.05, y: shot.y - 0.05, w: shot.w + 0.1, h: shot.h + 0.1, round: false, fill: { color: 'FFFFFF' }, line: { color: K.rule, width: 1 } });
    image('shot', { path: A('f02_dashboard.png'), ...shot });
    text('shot-cap', 'The dashboard of the application', { x: shot.x, y: shot.y + shot.h + 0.12, w: shot.w, h: 0.3, fontSize: 11, color: K.mute, align: 'center' });
  }

  // 2. Summary
  slide(null, null, NOTES['rm-tag#1'], { label: 'Summary' });
  text('title', 'Summary', { x: 0.6, y: 0.62, w: 12.1, h: 0.75, fontFace: HEAD, fontSize: 30, color: K.ink });
  const ITEMS = [
    ['Context', 'The host company and how a CAN bus works'], ['Problem', 'What is missing today and the existing tools'],
    ['Objectives and requirements', 'The objectives, the method and the requirements'], ['Proposed solution', 'Architecture, detection, models and explanation'],
    ['Demonstration', 'The real application on real recordings'], ['Validation', 'Two iterations on real recordings'],
    ['Limits', 'What is not proven yet'], ['Conclusion', 'Results and next steps'],
  ];
  ITEMS.forEach(([n, d], i) => {
    const x = i < 4 ? 0.9 : 7.05, y = 1.85 + (i % 4) * 1.22;
    text(`sm${i}-n`, String(i + 1), { x, y: y - 0.05, w: 0.6, h: 0.55, fontFace: HEAD, fontSize: 26, color: K.acc });
    text(`sm${i}`, titled(n, d, { ts: 20, ds: 14, dc: K.mute }), { x: x + 0.7, y, w: 4.95, h: 0.9 });
    if (i % 4 < 3) line(`sm${i}-r`, x, y + 1.04, 5.65, 0);
  });

  // 3. Host company
  question(0, 'Who is the host company?', 'Q:host');
  slide(0, 'Capgemini Engineering, my host company', NOTES['host#1']);
  image('host-logo', { path: A('capgemini.png'), ...await fit('capgemini.png', 0.6, 1.75, 3.6, 0.6, 'left') });
  text('host-txt', 'The engineering and research and development branch of the Capgemini group, which offers consulting and engineering services to many industries, the automotive sector among them.', { x: 0.6, y: 2.6, w: 5.4, h: 1.5, fontSize: 16 });
  [['Automotive division, Capgemini Tunisia', 'Works on vehicle software systems and on embedded engineering.'],
    ['Battery Management Systems team', 'Develops and validates the embedded software of battery management functions for electric and hybrid vehicles.'],
    ['My job: BMS QA tester for BMW Group', 'Work and study program since September 2024: full time, five days a week, with classes at ESPRIT on Saturdays.']].forEach(([t, d], i) => {
    const y = 1.75 + i * 1.35;
    text(`host-r${i}`, titled(t, d, { ts: 17, ds: 14 }), { x: 6.75, y, w: 5.98, h: 1.1 });
    if (i < 2) line(`host-r${i}-l`, 6.75, y + 1.2, 5.98, 0);
  });
  box('host-idea', [run('CANvisionNative is not a team deliverable. ', { bold: true, color: K.ink }), run('I started it in February 2026, alongside my job, from the difficulties of my daily validation work.', { color: K.body })],
    { x: 0.6, y: 5.6, w: 12.13, h: 0.9, fontSize: 15, align: 'left', margin: 14, fill: { color: K.accSoft }, line: { type: 'none' } });

  // 4. The CAN bus
  question(0, 'How do the computers of a car talk to each other?', 'Q:can');
  slide(0, 'One bus shared by every computer of the car', NOTES['can#1']);
  {
    const yH = 4.0, yL = 4.25;
    line('busH', 1.3, yH, 10.8, 0, { color: K.acc, width: 3 });
    line('busL', 1.3, yL, 10.8, 0, { color: K.blue, width: 3 });
    text('busH-l', 'CAN_H', { x: 0.55, y: yH - 0.14, w: 0.72, h: 0.28, fontSize: 11, bold: true, color: K.acc });
    text('busL-l', 'CAN_L', { x: 0.55, y: yL - 0.14, w: 0.72, h: 0.28, fontSize: 11, bold: true, color: K.blue });
    rect('term-l', { x: 1.18, y: 3.9, w: 0.12, h: 0.45, round: false, fill: { color: 'FFFFFF' }, line: { color: K.mute, width: 1 } });
    rect('term-r', { x: 12.1, y: 3.9, w: 0.12, h: 0.45, round: false, fill: { color: 'FFFFFF' }, line: { color: K.mute, width: 1 } });
    text('term-t', '120 Ω', { x: 12.28, y: 3.98, w: 0.8, h: 0.28, fontSize: 11, color: K.mute });
    const nodes = ['Motor controller', 'BMS', 'Brakes', 'Driver assistance', 'Dashboard', 'Telematics'];
    const cx = [2.9, 6.67, 10.43];
    nodes.forEach((n, i) => {
      const top = i < 3, c = cx[i % 3], y = top ? 1.8 : 5.15, bms = i === 1;
      line(`ecu${i}-stub`, c, top ? y + 0.95 : yL, 0, top ? yH - (y + 0.95) : y - yL, { color: K.mute, width: 1.25 });
      box(`ecu${i}`, n, { x: c - 1.25, y, w: 2.5, h: 0.95, fontSize: 16, bold: bms, color: bms ? K.acc : K.ink, fill: { color: bms ? K.accSoft : K.panel }, line: { color: bms ? K.acc : K.rule, width: bms ? 1.5 : 1 } });
    });
    arrow('fr-l', 1.8, 3.62, 4.3, 0, { color: K.warn, dash: 'dash', flipH: true });
    arrow('fr-r', 7.24, 3.62, 4.3, 0, { color: K.warn, dash: 'dash' });
    box('frame', '0x3F9', { x: 6.2, y: 3.42, w: 0.95, h: 0.4, fontFace: MONO, fontSize: 12, bold: true, color: 'FFFFFF', fill: { color: K.warn }, line: { type: 'none' }, margin: 0 });
    text('can-cap', 'Each ECU broadcasts short frames on one shared two-wire bus, and every node receives every frame.', { x: 0.6, y: 6.35, w: 12.13, h: 0.4, fontSize: 15, color: K.body, align: 'center' });
  }

  // 5. The CAN frame
  slide(0, 'A CAN frame does not say who sent it', NOTES['can#2']);
  {
    const segs = [['Identifier', '11 bits: what the frame is, and its priority', 3.0, K.accSoft], ['Length', 'number of data bytes', 1.8, K.panel],
      ['Data', 'up to 8 bytes; their meaning depends on the vehicle (DBC file)', 5.3, K.warnSoft], ['CRC', 'error check', 1.61, K.panel]];
    let x = 0.6;
    segs.forEach(([t, d, w, f], i) => {
      box(`seg${i}`, titled(t, d, { ts: 15, ds: 12 }), { x, y: 1.65, w, h: 1.05, align: 'left', valign: 'top', margin: 8, fill: { color: f }, line: { type: 'none' } });
      x += w + 0.14;
    });
    const row = (k, y, who, color, dashed, c) => {
      box(`snd${k}`, who, { x: 0.6, y, w: 2.2, h: 0.6, fontSize: 15, color, fill: { color: 'FFFFFF' }, line: { color, width: 1.25, dashType: dashed ? 'dash' : 'solid' } }, c);
      arrow(`snd${k}-a`, 2.86, y + 0.3, 0.48, 0, { color }, c);
      box(`fr${k}`, [run('0x3F9', { bold: true, color: K.acc }), run('   4E 00 00 00 00 00 00 00', { color: K.ink })], { x: 3.4, y, w: 4.4, h: 0.6, fontFace: MONO, fontSize: 14 }, c);
    };
    row(0, 3.05, 'BMS', K.acc, false);
    row(1, 3.8, 'Unknown device', K.red, true, 1);
    text('same', '=', { x: 7.95, y: 3.05, w: 0.6, h: 1.35, fontFace: HEAD, fontSize: 48, color: K.warn, align: 'center', valign: 'middle' }, 1);
    text('same-t', titled('Same identifier, same bytes.', 'Nothing in the frame tells the receivers who sent it.', { ts: 16, ds: 15 }), { x: 8.7, y: 3.05, w: 4.03, h: 1.35, valign: 'middle' }, 1);
    [['No sender identity', 'A frame does not say which ECU sent it.'], ['No authentication', 'Any node can send any identifier.'], ['No encryption', 'Every node reads every frame.']].forEach(([t, d], i) => {
      box(`miss${i}`, titled(t, d, { tc: K.red, ts: 16, ds: 14 }), { x: 0.6 + i * 4.11, y: 4.75, w: 3.91, h: 0.95, align: 'left', margin: 12, fill: { color: K.redSoft }, line: { type: 'none' } }, 2);
    });
    text('can-concl', 'The bus cannot tell a genuine frame from a forged one, or from a faulty one.', { x: 0.6, y: 5.95, w: 12.13, h: 0.45, fontFace: HEAD, fontSize: 19, color: K.ink, align: 'center' }, 2);
    text('can-src', 'CAN protocol: ISO 11898. Shown on real cars by Koscher et al. (2010) and Miller and Valasek (2015).', { x: 0.6, y: 6.45, w: 12.13, h: 0.3, fontSize: 11, color: K.mute, align: 'center' }, 2);
  }

  // 6. Problems
  question(1, 'What are the problems?', 'Q:prob');
  slide(1, 'The open issues of daily BMS validation work', NOTES['prob#1']);
  [['No live view of the traffic', 'Raw frames say what happened, not whether it should have happened.'],
    ['Weak replay', 'Tools replay frames without judging them, or accept only a few log formats.'],
    ['Scattered tools', 'An analyser, a diagnostic scanner and a spreadsheet, for one investigation.'],
    ['Alerts without explanation', 'A bare number, with no cause and no next step.']].forEach(([t, d], k) => {
    const y = 1.75 + k * 0.85;
    text(`pb${k}-n`, String(k + 1), { x: 0.6, y, w: 0.5, h: 0.6, fontFace: HEAD, fontSize: 24, color: K.acc, valign: 'middle' }, k + 1);
    text(`pb${k}-t`, t, { x: 1.2, y, w: 4.3, h: 0.6, fontFace: HEAD, fontSize: 19, color: K.ink, valign: 'middle' }, k + 1);
    text(`pb${k}-d`, d, { x: 5.6, y, w: 7.13, h: 0.6, fontSize: 15, valign: 'middle' }, k + 1);
    if (k < 3) line(`pb${k}-l`, 0.6, y + 0.74, 12.13, 0, {}, k + 1);
  });
  box('pb-sec', [run('Underneath all four: CAN has no security. ', { bold: true, color: K.red }), run('A toolchain that does not watch the bus cannot notice a malicious frame any more than a faulty one. A real but secondary motivation.', { color: K.body })],
    { x: 0.6, y: 5.35, w: 12.13, h: 1.1, fontSize: 15, align: 'left', margin: 16, fill: { color: K.redSoft }, line: { type: 'none' } }, 5);

  // 7. Existing tools
  question(1, 'What already exists?', 'Q:exist');
  slide(1, 'Four families of existing tools', NOTES['exist#1']);
  [['CAN analysers', 'Capture, DBC decoding and replay. The professional standard (CANoe, CANalyzer).', 'No judgement on whether a frame is normal for this vehicle.'],
    ['Intrusion detection research', 'Learns normal traffic and flags what deviates from it.', 'One signal, aims at attacks, rarely transfers to another vehicle, no explanation.'],
    ['Open source viewers', 'Lightweight and open source: SavvyCAN, candump.', 'Little control over replay, no notion of abnormal.'],
    ['Diagnostic scanners', 'Standard requests (OBD, UDS) to known ECUs.', 'Only see what they ask for, not the whole bus.']].forEach(([t, g, m], i) => {
    const x = 0.6 + i * 3.077, w = 2.9;
    rect(`ex${i}`, { x, y: 1.7, w, h: 3.85, fill: { color: 'FFFFFF' } });
    text(`ex${i}-t`, t, { x: x + 0.2, y: 1.88, w: w - 0.4, h: 0.7, fontFace: HEAD, fontSize: 17, color: K.ink });
    text(`ex${i}-g`, titled('Good at', g, { tc: K.green, ts: 12, ds: 13.5 }), { x: x + 0.2, y: 2.7, w: w - 0.4, h: 1.3 });
    text(`ex${i}-m`, titled('Missing', m, { tc: K.red, ts: 12, ds: 13.5 }), { x: x + 0.2, y: 4.05, w: w - 0.4, h: 1.35 });
  });
  box('ex-all', [run('Each tool covers one part. ', { bold: true, color: K.ink }), run('None of them combines decoding, replay, live monitoring, detection and explanation in one workflow.', { color: K.body })],
    { x: 0.6, y: 5.8, w: 12.13, h: 0.85, fontSize: 15, align: 'left', margin: 16, fill: { color: K.accSoft }, line: { type: 'none' } });

  // Problem statement: the question alone, then the question with the three needs it answers
  const hi = (t) => run(t, { color: K.acc });
  const STMT = () => [run('How can we give a BMS engineer '), hi('one view of the CAN traffic'), run(', '), hi('adapted to each vehicle'), run(', that '), hi('explains its own alerts'), run('?')];
  slide(1, 'Problem statement', NOTES['ps-label#1']);
  text('stmt', STMT(), { x: 1.0, y: 2.0, w: 11.33, h: 2.3, fontFace: HEAD, fontSize: 36, color: K.ink, align: 'center', valign: 'middle' });
  text('stmt-proof', '… and prove that it works on real recordings.', { x: 1.0, y: 4.5, w: 11.33, h: 0.5, fontSize: 19, italic: true, color: K.mute, align: 'center' });
  slide(1, 'Problem statement', NOTES['ps-label#2']);
  text('stmt', STMT(), { x: 1.0, y: 1.75, w: 11.33, h: 1.7, fontFace: HEAD, fontSize: 30, color: K.ink, align: 'center', valign: 'middle' });
  text('stmt-proof', '… and prove that it works on real recordings.', { x: 1.0, y: 3.5, w: 11.33, h: 0.45, fontSize: 17, italic: true, color: K.mute, align: 'center' });
  [['One view of the traffic', 'No live view, weak replay, scattered tools'], ['Adapted to each vehicle', 'Models rarely transfer from one vehicle to another'], ['Explains its own alerts', 'Alerts without explanation: a bare number, with no cause']].forEach(([t, d], c) => {
    box(`need${c}`, [br(t, { bold: true, color: K.acc, fontSize: 17 }), br('Answers', { color: K.mute, fontSize: 12 }), run(d, { color: K.body, fontSize: 14 })],
      { x: 0.6 + c * 4.11, y: 4.35, w: 3.91, h: 1.5, align: 'left', valign: 'top', margin: 14, fill: { color: 'FFFFFF' }, line: { color: K.rule, width: 1 } });
  });

  // 9. The idea
  slide(1, 'The idea', NOTES['h-base#2']);
  text('idea-name', [run('CANvision', { color: K.ink }), run('Native', { color: K.acc })], { x: 0.6, y: 1.65, w: 6.2, h: 0.8, fontFace: HEAD, fontSize: 40 });
  text('idea-def', 'One platform where a BMS engineer replays, monitors and understands the CAN traffic of a vehicle.', { x: 0.6, y: 2.5, w: 5.9, h: 0.95, fontSize: 19 });
  [['One view', 'replay, live monitoring and detection together'], ['Adapted to each vehicle', 'its own models and its own DBC file'], ['Explains its own alerts', 'in plain language, next to the score']].forEach(([t, d], k) => {
    const y = 3.75 + k * 0.9;
    rect(`idea${k}-bar`, { x: 0.6, y: y + 0.05, w: 0.07, h: 0.62, round: false, fill: { color: K.acc }, line: { type: 'none' } });
    text(`idea${k}`, titled(t, d, { ts: 17, ds: 14.5 }), { x: 0.85, y, w: 5.6, h: 0.75 });
  });
  {
    const shot = await fit('f08_anomaly_intel.png', 6.95, 1.7, 5.78, 4.55);
    rect('idea-frame', { x: shot.x - 0.05, y: shot.y - 0.05, w: shot.w + 0.1, h: shot.h + 0.1, round: false, fill: { color: 'FFFFFF' }, line: { color: K.rule, width: 1 } });
    image('idea-shot', { path: A('f08_anomaly_intel.png'), ...shot });
    text('idea-cap', 'In the application: the alerts, their layer scores and the explanation', { x: shot.x, y: shot.y + shot.h + 0.12, w: shot.w, h: 0.3, fontSize: 11, color: K.mute, align: 'center' });
  }

  // Objectives as in the thesis (section 1.7), then the methodology, then the requirements
  question(2, 'What are the objectives?', 'Q:obj');
  slide(2, 'What are the objectives?', NOTES['obj#1']);
  box('ob-gen', [br('General objective', { bold: true, color: K.acc, fontSize: 14 }), run('Design, build and validate a diagnostic platform for Battery Management Systems that gives an engineer one view of the CAN traffic, adapts to the vehicle being analysed, and explains its own alerts.', { color: K.ink, fontSize: 17 })],
    { x: 0.6, y: 1.6, w: 12.13, h: 1.4, align: 'left', valign: 'top', margin: 14, fill: { color: K.accSoft }, line: { type: 'none' } });
  text('ob-spec', 'Specific objectives', { x: 0.6, y: 3.22, w: 6, h: 0.3, fontSize: 14, bold: true, color: K.mute });
  [
    'A detection pipeline that combines a machine learning model with timing, payload and persistence checks',
    'The common log formats (CSV, MF4, candump, Vector, PCAN), a live simulator and live capture',
    'One model per vehicle, and in production only the models evaluated on a recording kept out of training',
    'A desktop client to import a log, replay it, review the anomalies and export a report',
    'An explanation layer, separate from detection, with rules and a language model',
    'A validation on real recordings with reproducible evidence, and every defect found corrected',
  ].forEach((t, i) => {
    const x = i < 3 ? 0.6 : 6.75, y = 3.64 + (i % 3) * 1.02;
    text(`ob${i}-n`, String(i + 1), { x, y: y - 0.04, w: 0.45, h: 0.5, fontFace: HEAD, fontSize: 22, color: K.acc });
    text(`ob${i}`, t, { x: x + 0.5, y, w: 5.45, h: 0.85, fontSize: 15, color: K.ink });
    if (i % 3 < 2) line(`ob${i}-r`, x, y + 0.92, 5.98, 0);
  });

  // 11. Methodology: the Unified Process, its phases and the iterations of construction
  slide(2, 'How did I organize the work?', NOTES['method#1']);
  {
    text('m-sub', 'The Unified Process', { x: 0.6, y: 1.42, w: 12.13, h: 0.36, fontSize: 15, bold: true, color: K.acc });
    const BY = 3.45, GAP = 0.12;
    const PH = [
      ['Inception', 'February', 'Use cases and risks', K.warn, 1.75],
      ['Elaboration', 'Feb to March', 'Architecture (M1)', K.blue, 2.15],
      ['Construction', 'March to September', '', K.acc, 6.25],
      ['Transition', 'Sept to October', 'Release and report', K.green, 1.74],
    ];
    let x = 0.6;
    PH.forEach(([name, when, what, col, w], p) => {
      text(`ph${p}`, name, { x, y: 2.45, w, h: 0.36, fontSize: 16, bold: true, color: col, align: 'center' });
      text(`ph${p}-w`, when, { x, y: 2.85, w, h: 0.3, fontSize: 12, color: K.mute, align: 'center' });
      rect(`ph${p}-bar`, { x, y: BY, w, h: 0.1, round: false, fill: { color: col }, line: { type: 'none' } });
      if (what) text(`ph${p}-d`, what, { x, y: 3.9, w, h: 0.34, fontSize: 14, color: K.ink, align: 'center' });
      if (p === 2) {
        ['First pipeline', 'Validation', 'Bench rig', 'Model rebuild'].forEach((t, k) => {
          const cx = x + w * (k + 0.5) / 4;
          box(`it${k}`, String(k + 1), { shape: pres.shapes.OVAL, rectRadius: undefined, x: cx - 0.24, y: BY + 0.05 - 0.24, w: 0.48, h: 0.48, fontSize: 13, bold: true, color: K.acc, margin: 0, fill: { color: 'FFFFFF' }, line: { color: K.acc, width: 1.75 } });
          text(`it${k}-t`, t, { x: cx - 0.78, y: 3.9, w: 1.56, h: 0.34, fontSize: 14, color: K.ink, align: 'center' });
        });
      }
      x += w + GAP;
    });
    text('m-why', [run('Why: ', { bold: true, color: K.acc }), run('iterative, driven by risks, architecture first.', { color: K.ink })], { x: 0.6, y: 5.25, w: 12.13, h: 0.42, fontSize: 18, align: 'center' });
    text('m-why2', 'Two unknowns at the start: how well a model generalises, and how many defects validation finds.', { x: 0.6, y: 5.75, w: 12.13, h: 0.36, fontSize: 14, color: K.mute, align: 'center' });
  }

  // Functional requirements: three slides that build up, as in the dark deck
  question(2, 'What must the platform do?', 'Q:fr');
  const FR = [['Import a recorded log', 'CSV, MF4, Vector .asc, candump .log, PCAN .txt into one frame stream'], ['Choose the vehicle', 'Its own models score the frames; its DBC file decodes them'],
    ['Replay the log', 'From 0.5× to 32× real time, with progress'], ['Detect anomalies', 'Score each frame; report what cannot be scored, with the reason'],
    ['Explain an alert', 'Dominant signal, likely cause, what to check'], ['Go live', 'Simulator, or a CAN adapter through python-can; record a session'],
    ['Export the results', 'CSV file and PDF report']];
  for (let step = 1; step <= 3; step++) {
    slide(2, 'What must the platform do?', NOTES[`fr#${step}`]);
    FR.slice(0, [2, 5, 7][step - 1]).forEach(([t, d], i) => {
      const y = 1.68 + i * 0.72;
      text(`fr${i}-n`, String(i + 1), { x: 0.6, y, w: 0.4, h: 0.32, fontSize: 15, bold: true, color: K.acc });
      text(`fr${i}`, titled(t, d, { ts: 15, ds: 12.5 }), { x: 1.05, y, w: 5.9, h: 0.66 });
    });
    const Y = [1.75, 2.65, 3.55, 4.45, 5.35, 6.25], h = 0.5;
    box('ch-log', 'Log file', { x: 7.6, y: Y[0], w: 2.3, h });
    arrow('ch-a0', 8.75, Y[0] + h, 0, Y[1] - Y[0] - h);
    if (step === 3) {
      box('ch-live', 'Simulator or adapter', { x: 10.35, y: Y[0], w: 2.38, h });
      arrow('ch-a0b', 11.54, Y[0] + h, 0, Y[1] - Y[0] - h);
    }
    const chain = ['Vehicle: models + DBC', ...(step >= 2 ? [step === 3 ? 'Replay or live stream' : 'Replay', 'Detection', 'Explanation'] : []), ...(step === 3 ? ['Export: PDF, CSV'] : [])];
    chain.forEach((t, k) => {
      const det = t === 'Detection';
      box(`ch${k}`, t, { x: 8.45, y: Y[k + 1], w: 3.3, h, bold: det, color: det ? K.acc : K.ink, fill: { color: det ? K.accSoft : K.panel }, line: { color: det ? K.acc : K.rule, width: 1 } });
      if (k < chain.length - 1) arrow(`ch${k}-a`, 10.1, Y[k + 1] + h, 0, Y[k + 2] - Y[k + 1] - h);
    });
  }

  // 12. Architecture
  question(3, 'What is the proposed solution?', 'Q:sol');
  slide(3, 'Architecture: the way the data flows', NOTES['sol#1']);
  {
    const cw = 1.82, gap = 0.24, y0 = 2.15, ch = 2.55, sx = (k) => 0.6 + k * (cw + gap);
    rect('be-box', { x: sx(1) - 0.12, y: y0 - 0.32, w: 4 * cw + 3 * gap + 0.24, h: ch + 0.55, fill: { color: 'FFFFFF', transparency: 100 }, line: { color: K.acc, width: 1.25, dashType: 'dash' } }, 6);
    text('be-box-t', 'Local Python backend (FastAPI)', { x: sx(1), y: y0 - 0.62, w: 5, h: 0.28, fontSize: 13, bold: true, color: K.acc }, 6);
    const ST_ = [['Traffic sources', 'CSV, MF4, ASC, candump and PCAN logs, a simulator or a CAN adapter'], ['Parser', 'one frame stream: time, identifier, payload; DBC decoding'],
      ['Features', '9 per identifier, over a window of 10 frames'], ['Detection engine', 'one Isolation Forest per identifier, plus timing, payload and persistence rules'],
      ['REST API', 'FastAPI, sessions in SQLite, explanations'], ['WPF client', '7 screens, PDF and CSV export']];
    ST_.forEach(([t, d], k) => {
      const det = k === 3;
      box(`st${k}`, titled(t, d, { tc: det ? K.acc : K.ink, ts: 15, ds: 12 }), { x: sx(k), y: y0, w: cw, h: ch, align: 'left', valign: 'top', margin: 10, fill: { color: det ? K.accSoft : K.panel }, line: { color: det ? K.acc : K.rule, width: det ? 1.5 : 1 } }, k || undefined);
      if (k) arrow(`st-a${k}`, sx(k) - gap + 0.02, y0 + ch / 2, gap - 0.04, 0, { color: K.acc }, k);
    });
    text('arch-cap', 'Two programs on one machine: a local Python backend and a Windows client, talking over HTTP.', { x: 0.6, y: 5.35, w: 12.13, h: 0.45, fontSize: 17, color: K.ink, align: 'center' }, 6);
  }

  // 13. How one frame is judged
  slide(3, 'How one frame is judged', NOTES['sol#2']);
  {
    const bw = 1.85, g = 0.21, by = 1.75, bh = 1.6, bx = (k) => 0.6 + k * (bw + g);
    [['CAN frame', 'from the bus or the log'], ['Features', '9 per identifier, window of 10'], ['Isolation Forest', 'the model of this identifier'],
      ['Four layers', 'timing 0.35, payload 0.35, model 0.20, persistence 0.10'], ['Fused score', 'weighted sum of the four layers'], ['Decision', 'alert if the score reaches 0.40']].forEach(([t, d], k) => {
      box(`dp${k}`, titled(t, d, { ts: 14.5, ds: 12 }), { x: bx(k), y: by, w: bw, h: bh, align: 'left', valign: 'top', margin: 9, fill: { color: k === 5 ? K.accSoft : K.panel }, line: { color: k === 5 ? K.acc : K.rule, width: 1 } });
      if (k < 5) arrow(`dp-a${k}`, bx(k) + bw + 0.02, by + bh / 2, g - 0.04, 0, { color: K.acc });
    });
    const ex = (k, y, label, score, res, color, soft) => {
      text(`ex${k}-l`, label, { x: 0.6, y, w: 3.4, h: 0.6, fontSize: 16, color: K.ink, valign: 'middle' }, k + 1);
      box(`ex${k}-s`, score, { x: 4.1, y, w: 2.5, h: 0.6, fontSize: 18, bold: true, color, fill: { color: soft }, line: { type: 'none' } }, k + 1);
      text(`ex${k}-r`, res, { x: 6.9, y, w: 5.83, h: 0.6, fontSize: 16, bold: true, color, valign: 'middle' }, k + 1);
    };
    ex(0, 3.75, 'Example: a normal frame', 'fused score 0.17', 'Normal: nothing happens', K.green, K.greenSoft);
    ex(1, 4.5, 'Example: an unusual frame', 'fused score 0.82', 'Alert, severity HIGH', K.red, K.redSoft);
    box('dp-n1', [run('Unscored frames are reported, never hidden. ', { bold: true, color: K.ink }), run('A frame with no model (warmup, sparse, unmodelled or unseen identifier) is counted as unresolved, with its reason.', { color: K.body })],
      { x: 0.6, y: 5.45, w: 5.95, h: 1.15, fontSize: 13, align: 'left', margin: 12, fill: { color: 'FFFFFF' } });
    box('dp-n2', [run('Offline analysis of a whole recording: ', { bold: true, color: K.ink }), run('same features and models; each frame is flagged when the score of its model passes 0.5.', { color: K.body })],
      { x: 6.78, y: 5.45, w: 5.95, h: 1.15, fontSize: 13, align: 'left', margin: 12, fill: { color: 'FFFFFF' } });
  }

  // 14. One model per identifier
  slide(3, 'One model per CAN identifier', NOTES['sol#3']);
  {
    const cw = 2.83, cy = 1.75, chh = 3.3, cx = (k) => 0.6 + k * 3.1;
    ['Frames of one identifier', '9 features', 'Isolation Forest', 'A score from 0 to 1'].forEach((t, k) => {
      rect(`mm${k}`, { x: cx(k), y: cy, w: cw, h: chh, fill: { color: 'FFFFFF' } });
      text(`mm${k}-t`, t, { x: cx(k) + 0.2, y: cy + 0.15, w: cw - 0.3, h: 0.4, fontFace: HEAD, fontSize: 15.5, color: K.ink });
      if (k < 3) arrow(`mm${k}-a`, cx(k) + cw + 0.02, cy + chh / 2, 0.23, 0, { color: K.acc });
    });
    text('mm0-s', 'here 0x3F9, in time order', { x: cx(0) + 0.2, y: cy + 0.55, w: cw - 0.3, h: 0.3, fontSize: 12, color: K.mute });
    text('mm0-f', ['35.000  4E 00 00 00', '35.200  4E 00 00 00', '35.400  4E 00 00 00', '35.600  4E 00 00 00', '35.800  4E 00 00 00'].map((l, i, a) => run(l, { breakLine: i < a.length - 1 })),
      { x: cx(0) + 0.2, y: cy + 1.0, w: cw - 0.3, h: 1.8, fontFace: MONO, fontSize: 12, color: K.acc, lineSpacing: 22 });
    text('mm1-b', [br('Timing ×3', { bold: true, color: K.warn, fontSize: 13 }), br('time between frames, its rolling mean and std', { fontSize: 12.5, paraSpaceAfter: 10 }),
      br('Payload ×6', { bold: true, color: K.blue, fontSize: 13 }), run('byte change, its rolling mean, std and max; changed bytes; entropy', { fontSize: 12.5 })], { x: cx(1) + 0.2, y: cy + 0.6, w: cw - 0.4, h: 2.0 });
    text('mm1-w', 'over a window of 10 frames', { x: cx(1) + 0.2, y: cy + 2.8, w: cw - 0.3, h: 0.3, fontSize: 12, color: K.mute });
    const bx = cx(2) + 0.3, by = cy + 0.65, bw = cw - 0.6, bh = 1.75;
    rect('iso-box', { x: bx, y: by, w: bw, h: bh, round: false, fill: { color: K.panel }, line: { color: K.rule, width: 1 } });
    [[0.30, 0.52], [0.40, 0.46], [0.50, 0.50], [0.58, 0.57], [0.36, 0.60], [0.46, 0.58], [0.54, 0.66], [0.28, 0.68], [0.40, 0.70], [0.50, 0.75], [0.60, 0.72], [0.33, 0.80], [0.45, 0.84], [0.56, 0.86]]
      .forEach(([px, py], k) => dot(`iso-p${k}`, bx + px * bw, by + py * bh, 0.1, K.mute, 1));
    dot('iso-odd', bx + 0.88 * bw, by + 0.17 * bh, 0.15, K.red, 1);
    line('iso-v', bx + 0.78 * bw, by, 0, bh, { color: K.acc, width: 1.25, dash: 'dash' }, 1);
    line('iso-h', bx + 0.78 * bw, by + 0.33 * bh, 0.22 * bw, 0, { color: K.acc, width: 1.25, dash: 'dash' }, 1);
    text('iso-v-n', 'cut 1', { x: bx + 0.78 * bw - 0.5, y: by + bh - 0.26, w: 0.45, h: 0.2, fontFace: MONO, fontSize: 9, color: K.acc, align: 'right' }, 1);
    text('iso-h-n', 'cut 2', { x: bx + 0.78 * bw + 0.02, y: by + 0.33 * bh + 0.04, w: 0.42, h: 0.2, fontFace: MONO, fontSize: 9, color: K.acc }, 1);
    text('mm2-c', '200 trees. An unusual frame is isolated in very few cuts.', { x: cx(2) + 0.2, y: cy + 2.5, w: cw - 0.3, h: 0.7, fontSize: 12.5 });
    const sx = cx(3) + 0.25, sw = cw - 0.5, sy = cy + 1.1;
    [K.green, K.acc, K.warn, K.red].forEach((c, k) => rect(`sc${k}`, { x: sx + k * sw / 4, y: sy, w: sw / 4, h: 0.3, round: false, fill: { color: c }, line: { type: 'none' } }));
    line('sc-mk', sx + sw / 2, sy - 0.2, 0, 0.72, { color: K.ink, width: 2 });
    text('sc-0', '0', { x: sx - 0.1, y: sy + 0.36, w: 0.3, h: 0.25, fontSize: 12, color: K.mute });
    text('sc-5', '0.5', { x: sx + sw / 2 - 0.25, y: sy + 0.55, w: 0.5, h: 0.25, fontSize: 12, bold: true, color: K.ink, align: 'center' });
    text('sc-1', '1', { x: sx + sw - 0.2, y: sy + 0.36, w: 0.3, h: 0.25, fontSize: 12, color: K.mute, align: 'right' });
    text('mm3-c', 'The threshold, 0.5, is set so that 2 % of the training rows pass it. Above it, the frame is flagged.', { x: cx(3) + 0.2, y: cy + 2.0, w: cw - 0.3, h: 1.1, fontSize: 12.5 });
    ['At least 1,000 training rows per identifier, or no model', 'Not scored, and said so: warmup, sparse, unmodelled or unseen identifier', 'The timing features carry 64 % of the splits'].forEach((t, k) => {
      box(`mmc${k}`, t, { x: 0.6 + k * 4.11, y: 5.35, w: 3.91, h: 1.0, fontSize: 13.5, color: K.ink, fill: { color: K.accSoft }, line: { type: 'none' } });
    });
  }

  // 15. One model per vehicle
  slide(3, 'Why one model per vehicle?', NOTES['sol#4']);
  {
    const V = [
      { k: 'kia', name: 'Kia EV6', meta: '161 identifier models, 448,198 training frames', ids: ['0x36', '0x37', '0x38', '0x39', '0x4B'], more: '… 161 models in total', x: 0.9, c: 0 },
      { k: 'jag', name: 'Jaguar I-PACE', meta: '46 identifier models, 233,598 training frames', ids: ['0x36', '0x41', '0x44', '0x50', '0x63'], more: '… 46 models in total', x: 8.15, c: 1 },
    ];
    for (const v of V) {
      const c = v.c || undefined;
      text(`${v.k}-n`, titled(v.name, v.meta, { ts: 19, ds: 13, dc: K.mute }), { x: v.x, y: 1.7, w: 4.4, h: 0.85 }, c);
      v.ids.forEach((id, i) => {
        const y = 2.75 + i * 0.52;
        box(`${v.k}${i}-id`, id, { x: v.x, y, w: 1.0, h: 0.4, fontFace: MONO, fontSize: 13, bold: true, color: K.acc, fill: { color: K.accSoft }, line: { type: 'none' }, margin: 0 }, c);
        arrow(`${v.k}${i}-a`, v.x + 1.06, y + 0.2, 0.5, 0, {}, c);
        box(`${v.k}${i}-m`, 'its own Isolation Forest', { x: v.x + 1.62, y, w: 2.65, h: 0.4, fontSize: 12.5, margin: 0 }, c);
      });
      text(`${v.k}-more`, v.more, { x: v.x, y: 5.4, w: 4.3, h: 0.3, fontSize: 12, color: K.mute }, c);
    }
    rect('kia-hl', { x: 0.82, y: 2.68, w: 4.53, h: 0.54, fill: { color: 'FFFFFF', transparency: 100 }, line: { color: K.warn, width: 1.75 } }, 2);
    rect('jag-hl', { x: 8.07, y: 2.68, w: 4.53, h: 0.54, fill: { color: 'FFFFFF', transparency: 100 }, line: { color: K.warn, width: 1.75 } }, 2);
    line('hl-link', 5.37, 2.95, 2.68, 0, { color: K.warn, width: 1.5, dash: 'dash' }, 2);
    box('hl-box', [br('0x36 on both cars', { bold: true, color: K.warn }), br('Kia: 4,871 rows, 9 features'), br('Jaguar: 3,257 rows, 7 features'), run('Two different models', { color: K.mute })],
      { x: 5.55, y: 3.3, w: 2.33, h: 1.95, fontSize: 12.5, color: K.ink, fill: { color: K.warnSoft }, line: { type: 'none' }, paraSpaceAfter: 4 }, 2);
    text('veh-msg', 'CAN traffic depends on the vehicle, so the models are vehicle specific.', { x: 0.6, y: 5.95, w: 12.13, h: 0.5, fontFace: HEAD, fontSize: 19, color: K.ink, align: 'center' }, 3);
  }

  // 16. Explanation
  slide(3, 'Explaining an alert', NOTES['sol#6']);
  {
    const fw = 2.75, fg = 0.38, fy = 1.7, fh = 1.4, fx = (k) => 0.6 + k * (fw + fg);
    const F = [['Alert', [run('0x063', { fontFace: MONO, bold: true, color: K.ink }), br('  score 0.535', { fontFace: MONO }), run('from the detection engine')], K.red, K.redSoft],
      ['Context', [run('decoded signals, layer scores, temporal pattern, knowledge base')], K.ink, K.panel],
      ['Explainer', [run('Gemini; if it cannot be reached, a local Ollama model; if neither answers, rules')], K.blue, K.blueSoft],
      ['Diagnosis', [run('dominant signal, likely cause, what to check')], K.acc, K.accSoft]];
    F.forEach(([t, d, c, soft], k) => {
      box(`xf${k}`, [br(t, { bold: true, color: c, fontSize: 16 }), ...d.map((r) => ({ text: r.text, options: { fontSize: 12.5, color: K.body, ...r.options } }))],
        { x: fx(k), y: fy, w: fw, h: fh, align: 'left', valign: 'top', margin: 10, fill: { color: soft }, line: { type: 'none' } }, k ? 1 : undefined);
      if (k) arrow(`xf-a${k}`, fx(k) - fg + 0.04, fy + fh / 2, fg - 0.08, 0, { color: K.mute }, 1);
    });
    const shot = await fit('f08_explain_crop.png', 0.6, 3.45, 6.2, 2.75);
    rect('x-frame', { x: shot.x - 0.04, y: shot.y - 0.04, w: shot.w + 0.08, h: shot.h + 0.08, round: false, fill: { color: 'FFFFFF' }, line: { color: K.rule, width: 1 } }, 2);
    image('x-shot', { path: A('f08_explain_crop.png'), ...shot }, 2);
    text('x-cap', 'In the application: the explanation of the alert on 0x063', { x: 0.6, y: shot.y + shot.h + 0.08, w: 6.2, h: 0.28, fontSize: 11, color: K.mute, align: 'center' }, 2);
    text('x-r1', 'AI explains.', { x: 7.25, y: 3.5, w: 5.48, h: 0.6, fontFace: HEAD, fontSize: 28, color: K.ink }, 3);
    text('x-r2', 'The detection engine decides.', { x: 7.25, y: 4.08, w: 5.48, h: 0.6, fontFace: HEAD, fontSize: 28, color: K.acc }, 3);
    text('x-r3', [br('The detection engine sets the scores, the flags and the severities.', { paraSpaceAfter: 6 }), run('The explanation is words only: it never changes a score, a flag or a severity, and its numbers are checked against the alert.')],
      { x: 7.25, y: 4.9, w: 5.48, h: 1.5, fontSize: 14 }, 3);
  }

  // 17. Demo
  question(4, 'Can we see it working?', 'Q:demo');
  slide(4, 'The real application', NOTES['demo#1']);
  {
    const w = 9.6, h = w * 9 / 16, x = (13.333 - w) / 2, y = 1.5;
    rect('vid-frame', { x: x - 0.04, y: y - 0.04, w: w + 0.08, h: h + 0.08, round: false, fill: { color: '0A1420' }, line: { color: K.rule, width: 1 } });
    cur.s.addMedia({ type: 'video', path: A('CANvision_demo.mp4'), cover: 'data:image/jpeg;base64,' + fs.readFileSync(A('CANvision_demo_poster.jpg')).toString('base64'), x, y, w, h });
  }

  // 18. Validation, first iteration
  const DEFECTS = ['The selected vehicle model was never used for scoring', 'Driving state: 99.93 % "parking" for an hour of driving', 'Diagnostic fields dominated the cause shown to the analyst',
    'Replay formats other than CSV bypassed the common parser', 'A polling timer stayed stopped after an import', 'The explanation cache returned another session\'s text'];
  const subtitle = (t, color) => text('sub', t, { x: 0.6, y: 1.42, w: 12.13, h: 0.36, fontSize: 15, bold: true, color });
  question(5, 'How do we know it works?', 'Q:val');
  slide(5, 'How do we know it works?', NOTES['val#1'], { label: 'Iteration 2: validation' });
  {
    subtitle('Iteration 2: the first pipeline on a one hour Kia EV6 recording (97,741 frames)', K.warn);
    text('v-count', '15,945', { x: 0.6, y: 1.95, w: 5.6, h: 0.95, fontFace: HEAD, fontSize: 52, color: K.warn });
    text('v-lbl', 'alerts, 16.3 % of the frames', { x: 0.6, y: 2.9, w: 5.6, h: 0.38, fontSize: 16, color: K.ink });
    text('v-why', 'Instead of raising the threshold, we attributed every alert to the layer that dominated it:', { x: 0.6, y: 3.42, w: 5.6, h: 0.62, fontSize: 13.5 });
    const parts = [[61.42, K.acc, 'Machine learning 61.42 %', 'wrong model, wrong driving state'], [31.51, K.warn, 'Timing 31.51 %', 'irregular UDS polling'], [7.07, K.blue, 'Payload 7.07 %', 'real sensor variation']];
    let px = 0.6;
    parts.forEach(([p, c], k) => { const w = 5.6 * p / 100; rect(`v-b${k}`, { x: px, y: 4.15, w, h: 0.28, round: false, fill: { color: c }, line: { type: 'none' } }); px += w; });
    parts.forEach(([, c, t, d], k) => {
      const y = 4.62 + k * 0.45;
      rect(`v-k${k}`, { x: 0.6, y: y + 0.09, w: 0.2, h: 0.2, round: false, fill: { color: c }, line: { type: 'none' } });
      text(`v-t${k}`, [run(t + '   ', { bold: true, color: K.ink }), run(d)], { x: 0.95, y, w: 5.3, h: 0.38, fontSize: 13.5, valign: 'middle' });
    });
    text('v-fx-h', 'Six silent defects', { x: 6.85, y: 1.95, w: 5.9, h: 0.45, fontFace: HEAD, fontSize: 19, color: K.ink }, 1);
    DEFECTS.forEach((t, k) => {
      const y = 2.55 + k * 0.52;
      text(`v-f${k}-n`, String(k + 1), { x: 6.85, y, w: 0.35, h: 0.45, fontSize: 15, bold: true, color: K.red, valign: 'middle' }, 1);
      text(`v-f${k}`, t, { x: 7.25, y, w: 5.48, h: 0.45, fontSize: 14, color: K.ink, valign: 'middle' }, 1);
    });
    text('v-note', 'None of them crashed. Each appeared only when the output was compared with a fact known independently, such as the car being driven.', { x: 6.85, y: 5.75, w: 5.88, h: 0.75, fontSize: 13, italic: true, color: K.mute }, 1);
  }

  // 19. Validation, corrections
  slide(5, 'How do we know it works?', NOTES['val#2'], { label: 'After the corrections' });
  {
    subtitle('Iteration 2: six corrections, the same recording, the same threshold', K.green);
    text('v2-count', '11,971', { x: 0.6, y: 1.95, w: 5.6, h: 0.95, fontFace: HEAD, fontSize: 52, color: K.green });
    text('v2-lbl', 'alerts after the corrections, against 15,945 before', { x: 0.6, y: 2.9, w: 5.8, h: 0.38, fontSize: 16, color: K.ink });
    rect('v2-before', { x: 0.6, y: 3.45, w: 5.3, h: 0.28, round: false, fill: { color: 'FFFFFF', transparency: 100 }, line: { color: K.warn, width: 1, dashType: 'dash' } });
    rect('v2-after', { x: 0.6, y: 3.45, w: 5.3 * 11971 / 15945, h: 0.28, round: false, fill: { color: K.green }, line: { type: 'none' } });
    text('v2-pct', '−25 %', { x: 0.6 + 5.3 * 11971 / 15945 + 0.1, y: 3.43, w: 1.2, h: 0.32, fontSize: 14, bold: true, color: K.green, valign: 'middle' });
    [['Saturated model score (≥ 0.999)', '77.6 to 78.6 %', '0.0 %'], ['Replay throughput', '≈ 143 frames/s', '≈ 194.6 frames/s'], ['Driving state', '99.93 % parking', '99.92 % driving']].forEach(([t, b, a], k) => {
      const y = 4.0 + k * 0.55;
      text(`v2-ba${k}-t`, t, { x: 0.6, y, w: 2.75, h: 0.45, fontSize: 12.5, color: K.mute, valign: 'middle' });
      text(`v2-ba${k}-v`, [run(b), run(' → '), run(a, { bold: true, color: K.green })], { x: 3.35, y, w: 3.3, h: 0.45, fontSize: 13, valign: 'middle' });
    });
    text('v2-fx-h', 'Six defects, six corrections', { x: 6.85, y: 1.95, w: 5.9, h: 0.45, fontFace: HEAD, fontSize: 19, color: K.ink });
    DEFECTS.forEach((t, k) => {
      const y = 2.55 + k * 0.52;
      text(`v2-f${k}-n`, '✓', { x: 6.85, y, w: 0.35, h: 0.45, fontSize: 15, bold: true, color: K.green, valign: 'middle' });
      text(`v2-f${k}`, t, { x: 7.25, y, w: 5.48, h: 0.45, fontSize: 14, color: K.body, valign: 'middle' });
    });
    box('v2-concl', [run('The threshold was never touched. ', { bold: true, color: K.ink }), run('The design stayed fragile, so I rebuilt every model with a stricter pipeline in iteration 4.', { color: K.body })],
      { x: 0.6, y: 5.8, w: 12.13, h: 0.72, fontSize: 14, align: 'left', margin: 14, fill: { color: K.accSoft }, line: { type: 'none' } });
    text('v2-foot', 'Counts measured after the four data-driven fixes (1 to 4); fixes 5 and 6 were in the client and the explanation cache.', { x: 0.6, y: 6.6, w: 12.13, h: 0.28, fontSize: 10.5, italic: true, color: K.mute });
  }

  // 20. Validation, second iteration
  const chartStyle = {
    showValue: true, dataLabelPosition: 'outEnd', dataLabelColor: K.ink, dataLabelFontFace: FONT,
    catAxisLabelColor: K.body, catAxisLabelFontSize: 12, catAxisLabelFontFace: FONT, catAxisLineShow: true, catAxisLineColor: K.rule,
    valAxisLabelColor: K.mute, valAxisLabelFontSize: 10, valAxisLabelFontFace: FONT, valAxisLineShow: false, valAxisMinVal: 0,
    valGridLine: { color: 'E5E8EC', size: 0.75 }, catGridLine: { style: 'none' },
    showLegend: true, legendPos: 'b', legendColor: K.body, legendFontSize: 11, legendFontFace: FONT,
    showTitle: true, titleColor: K.ink, titleFontSize: 14, titleFontFace: FONT,
  };
  slide(5, 'How do we know it works?', NOTES['val#3'], { label: 'Iteration 4: final models' });
  {
    subtitle('Iteration 4: the final models on recordings they never saw', K.acc);
    const cats = ['Jaguar I-PACE', 'Kia EV6', 'Nissan Leaf 2019', 'ROAD ambient'];
    // Drawn with shapes, not a chart object: a chart embeds an Excel workbook, and PowerPoint refuses
    // to open it on a computer where Excel is missing or WPS handles spreadsheets.
    {
      const vals = [3.09, 2.59, 0.60, 6.09], X0 = 1.15, X1 = 7.75, Y0 = 2.65, Y1 = 5.75, VMAX = 7;
      const yv = (v) => Y1 - (v / VMAX) * (Y1 - Y0), slot = (X1 - X0) / 4, bw = 0.85;
      text('h-title', 'Holdout frames flagged (%)', { x: 0.6, y: 2.0, w: 7.3, h: 0.36, fontSize: 14, color: K.ink, align: 'center' });
      for (let v = 0; v <= VMAX; v++) {
        line(`h-grid${v}`, X0, yv(v), X1 - X0, 0, { color: 'E5E8EC', width: 0.75 });
        text(`h-ax${v}`, String(v), { x: 0.6, y: yv(v) - 0.12, w: 0.45, h: 0.24, fontSize: 10, color: K.mute, align: 'right' });
      }
      vals.forEach((v, k) => {
        const cx = X0 + slot * (k + 0.5);
        rect(`h-bar${k}`, { x: cx - bw / 2, y: yv(v), w: bw, h: Y1 - yv(v), round: false, fill: { color: K.acc }, line: { type: 'none' } });
        text(`h-val${k}`, v.toFixed(2), { x: cx - 0.6, y: yv(v) - 0.32, w: 1.2, h: 0.28, fontSize: 12, color: K.ink, align: 'center' });
        text(`h-cat${k}`, cats[k], { x: cx - slot / 2, y: Y1 + 0.08, w: slot, h: 0.28, fontSize: 12, color: K.body, align: 'center' });
      });
      line('h-target', X0, yv(2), X1 - X0, 0, { color: K.warn, width: 2, dash: 'dash' });
      rect('h-lg1', { x: 2.0, y: 6.24, w: 0.22, h: 0.16, round: false, fill: { color: K.acc }, line: { type: 'none' } });
      text('h-lg1t', 'Holdout frames flagged', { x: 2.3, y: 6.18, w: 2.2, h: 0.28, fontSize: 11, color: K.body });
      line('h-lg2', 4.6, 6.32, 0.35, 0, { color: K.warn, width: 2, dash: 'dash' });
      text('h-lg2t', 'Calibration target, 2 %', { x: 5.03, y: 6.18, w: 2.4, h: 0.28, fontSize: 11, color: K.body });
    }
    [[titled('296 identifier models', 'for 4 vehicles', { ts: 15, ds: 14 }), 2.0], [titled('3,436,061 training frames', '1,130,500 holdout frames, no overlap', { ts: 15, ds: 14 }), 2.95],
      [[run('ROAD at 6.09 %: ', { bold: true, color: K.ink }), run('ID 0x193 never changes in training but changes on the highway. A coverage gap, not a threshold problem.')], 3.95],
      [[run('Held back: MG ZS EV, ', { bold: true, color: K.red }), run('43.6 % flagged, with 78 % of its holdout on identifiers it never saw.')], 5.2]].forEach(([t, y], k) => {
      text(`hc${k}`, t, { x: 8.3, y, w: 4.43, h: k < 2 ? 0.8 : 1.15, fontSize: 14 });
    });
    text('h-foot', 'No attack labels: a flagged rate on unlabelled recordings is not a false positive rate, a precision or a recall.', { x: 0.6, y: 6.6, w: 12.13, h: 0.3, fontSize: 11.5, italic: true, color: K.mute });
  }

  // 21. Limits
  question(6, 'What are its limits?', 'Q:lim');
  slide(6, 'Four limits, stated plainly', NOTES['lim#1']);
  [['Live capture', 'Tested on a bench rig only, not on a vehicle.', 'The transport of live frames is validated; detection on a live vehicle bus is not measured.'],
    ['Live performance', 'About 200 to 260 frames per second.', 'Enough for a slow bus such as the Nissan Leaf (about 100 frames/s), not for buses that carry thousands.'],
    ['Holdout data', 'No attack labels.', 'We report flagged rates, not a detection rate, a precision or a recall.'],
    ['Vehicle coverage', 'Rare identifiers get no model.', 'Jaguar I-PACE: 82.6 % of the holdout frames scored. One model held back (MG ZS EV).']].forEach(([l, s1, s2], k) => {
    const y = 1.75 + k * 1.12;
    text(`lm${k}-l`, l, { x: 0.6, y, w: 3.0, h: 0.9, fontSize: 16, bold: true, color: K.warn, valign: 'middle' });
    text(`lm${k}-t`, titled(s1, s2, { ts: 18, ds: 14.5 }), { x: 3.8, y, w: 8.93, h: 0.9, valign: 'middle' });
    if (k < 3) line(`lm${k}-r`, 0.6, y + 1.01, 12.13, 0);
  });
  text('lm-foot', 'Each limit is measured and stated in the report.', { x: 0.6, y: 6.35, w: 12.13, h: 0.35, fontSize: 13, italic: true, color: K.mute, align: 'center' });

  // 22. Conclusion
  question(7, 'What can we conclude?', 'Q:conc');
  slide(7, 'Delivered, and what I learned', NOTES['conc#1']);
  text('cc-d-h', 'Delivered', { x: 0.6, y: 1.7, w: 6.8, h: 0.45, fontFace: HEAD, fontSize: 19, color: K.green });
  ['A Windows client and a Python backend: recorded logs, a live simulator and live capture', '4 vehicle models, 296 identifier models, evaluated on 1,130,500 frames they never saw',
    'A training pipeline that refuses a model failing its evaluation', 'Explanations in plain language, kept apart from detection', 'A bench rig with its firmware, and 318 + 86 automated tests'].forEach((t, k) => {
    const y = 2.3 + k * 0.7;
    text(`cc-d${k}-c`, '✓', { x: 0.6, y, w: 0.35, h: 0.55, fontSize: 16, bold: true, color: K.green, valign: 'middle' });
    text(`cc-d${k}`, t, { x: 1.0, y, w: 6.4, h: 0.55, fontSize: 15, color: K.ink, valign: 'middle' });
  });
  rect('cc-l', { x: 7.85, y: 1.7, w: 4.88, h: 4.2, fill: { color: K.accSoft }, line: { type: 'none' } });
  text('cc-l-h', 'What I learned', { x: 8.15, y: 1.9, w: 4.3, h: 0.45, fontFace: HEAD, fontSize: 19, color: K.acc });
  ['The most costly defects were the silent ones: none of them crashed.', 'A holdout is only meaningful when the split is made by recording, not by frame.', 'A flagged rate on unlabelled data is not a detection rate.'].forEach((t, k) => {
    text(`cc-l${k}`, t, { x: 8.15, y: 2.5 + k * 1.08, w: 4.35, h: 0.95, fontSize: 15, color: K.ink });
  });
  text('cc-q', '"A detection system is only as trustworthy as the evidence behind each of its numbers."', { x: 0.6, y: 6.15, w: 12.13, h: 0.55, fontFace: HEAD, fontSize: 17, italic: true, color: K.ink, align: 'center', valign: 'middle' });

  // 23. Next steps
  slide(7, 'What comes next?', NOTES['persp#1']);
  [['Live capture on a real vehicle', 'The first step: it closes milestone M2.'], ['Labelled attacks', 'Evaluate the final models on recordings with labelled attacks, such as the ROAD dataset, to measure what they detect as well as what they flag.'],
    ['A faster live path', 'Score several frames at once or use fewer trees, with each change measured on the holdout recordings.'], ['More recordings per vehicle', 'A holdout for every vehicle, and a model for more of the rare identifiers.']].forEach(([t, d], k) => {
    const x = k % 2 ? 6.78 : 0.6, y = k < 2 ? 1.75 : 4.2, w = 5.95, h = 2.2;
    rect(`pp${k}`, { x, y, w, h, fill: { color: 'FFFFFF' } });
    text(`pp${k}-n`, String(k + 1), { x: x + 0.3, y: y + 0.25, w: 0.6, h: 0.6, fontFace: HEAD, fontSize: 28, color: K.acc });
    text(`pp${k}-t`, titled(t, d, { ts: 18, ds: 14.5 }), { x: x + 1.0, y: y + 0.3, w: w - 1.3, h: h - 0.5 });
  });

  // 24. Closing
  slide(null, null, NOTES['title#1'], { plain: true, label: 'Closing' });
  text('end-name', [run('CANvision', { color: K.ink }), run('Native', { color: K.acc })], { x: 1.2, y: 1.9, w: 10.93, h: 1.0, fontFace: HEAD, fontSize: 54, align: 'center' });
  text('end-tag', 'From CAN frames to explainable diagnostics.', { x: 1.2, y: 3.0, w: 10.93, h: 0.6, fontSize: 24, color: K.ink, align: 'center' });
  text('end-verbs', 'Diagnose, monitor, detect, explain and validate', { x: 1.2, y: 3.65, w: 10.93, h: 0.4, fontSize: 16, color: K.mute, align: 'center' });
  text('end-thx', [run('Thank you for your attention.  ', { color: K.body }), run('Questions?', { color: K.acc, bold: true })], { x: 1.2, y: 4.75, w: 10.93, h: 0.55, fontSize: 22, align: 'center' }, 1);
  image('end-esprit', { path: A('esprit.png'), ...await fit('esprit.png', 4.6, 6.0, 1.9, 0.62, 'right') }, 1);
  line('end-sep', 6.67, 6.05, 0, 0.5, { color: K.rule }, 1);
  image('end-capg', { path: A('capgemini.png'), ...await fit('capgemini.png', 6.85, 6.12, 2.0, 0.38, 'left') }, 1);

  // ---------- hidden backup slides ----------
  const BK = { hidden: true };
  slide(2, 'How should it behave?', 'Six non functional requirements. Performance: an offline analysis of hundreds of thousands of frames in a few minutes, and live scoring that keeps up with the bus; the second one is only met for slow buses. Reliability: a defect is fixed with evidence, never by tuning a threshold. Usability: no machine learning background needed. Format independence: every format becomes the same frame stream. Extensibility: a new vehicle only needs a DBC file and a model that passes the checks. And graceful degradation: without a language model, the explanation falls back to rules.', { ...BK, label: 'Non functional requirements' });
  [['Performance', 'Offline: hundreds of thousands of frames in a few minutes. Live: keep up with the bus.'], ['Reliability', 'A defect is fixed with evidence, never by tuning a threshold until the numbers look better.'],
    ['Usability', 'No machine learning background needed to read an alert and its explanation.'], ['Format independence', 'Every log format enters the pipeline as the same frame stream.'],
    ['Extensibility', 'A new vehicle needs only a DBC file and a model folder that passes the promotion checks.'], ['Graceful degradation', 'No language model reachable: a rule based explanation instead of a failure.']].forEach(([t, d], i) => {
    const x = 0.6 + (i % 3) * 4.11, y = i < 3 ? 1.7 : 3.95;
    box(`nf${i}`, titled(t, d, { tc: K.acc, ts: 17, ds: 14 }), { x, y, w: 3.91, h: 2.0, align: 'left', valign: 'top', margin: 14, fill: { color: 'FFFFFF' } });
  });
  text('nf-plat', 'Platform: Windows 10 or 11 with .NET Framework 4.8, a local Python 3.11 backend, and a python-can adapter only for live capture', { x: 0.6, y: 6.2, w: 12.13, h: 0.35, fontSize: 13, color: K.mute, align: 'center' });

  slide(3, 'From recordings to a model in production', 'A model enters production only through a strict pipeline.\n\nThe recordings of a vehicle are split by recording, not by frame, into training and holdout, and we check that no recording is on both sides. We compute the features, fit one forest per identifier that has at least 1,000 rows, set its threshold at 2 percent, and write all of this in a manifest, so we can always prove how a model was built.\n\nThen we score the holdout recording, which the model has never seen. If the result is acceptable, the model is promoted. If not, it is held back: this is what happened to the MG ZS EV, which flagged 43.6 percent of its holdout.\n\nToday, four vehicles are in production, with 296 identifier models, trained on about 3.4 million frames and evaluated on 1.1 million frames they never saw.', { ...BK, label: 'Training and promotion pipeline' });
  {
    const tx = (i) => 0.6 + i * 2.45;
    [['Recordings of one vehicle', ''], ['Split by recording', 'training or holdout, no overlap'], ['9 features', 'per identifier'], ['One forest per identifier', 'at least 1,000 rows'], ['Threshold at 2 %', 'written in a manifest']].forEach(([t, d], i) => {
      box(`tp${i}`, d ? titled(t, d, { ts: 14, ds: 11.5 }) : t, { x: tx(i), y: 1.8, w: 2.2, h: 1.05, fontSize: 14 });
      if (i < 4) arrow(`tp${i}-a`, tx(i) + 2.22, 2.32, 0.21, 0, { color: K.acc });
    });
    arrow('tp-down', tx(4) + 1.1, 2.87, 0, 0.5, { color: K.acc });
    box('tp-hold', 'Score the holdout recording', { x: tx(4), y: 3.4, w: 2.2, h: 1.0, fill: { color: K.accSoft }, line: { color: K.acc, width: 1 } });
    box('tp-dec', 'Acceptable?', { shape: pres.shapes.DIAMOND, rectRadius: undefined, x: tx(3), y: 3.27, w: 2.2, h: 1.26, fontSize: 13, margin: 0, fill: { color: 'FFFFFF' }, line: { color: K.mute, width: 1 } });
    arrow('tp-hold-a', tx(3) + 2.2, 3.9, 0.25, 0, { color: K.acc, flipH: true });
    text('tp-yes', 'yes', { x: tx(2) + 2.1, y: 3.55, w: 0.5, h: 0.3, fontSize: 12, bold: true, color: K.green, align: 'center' });
    arrow('tp-yes-a', tx(2) + 2.2, 3.9, 0.25, 0, { color: K.green, flipH: true });
    box('tp-prom', titled('Promote to production', 'model files in Git LFS', { ts: 14, ds: 11.5 }), { x: tx(2) - 0.1, y: 3.4, w: 2.3, h: 1.0, fill: { color: K.greenSoft }, line: { type: 'none' } });
    arrow('tp-no-a', tx(3) + 1.1, 4.55, 0, 0.45, { color: K.red });
    text('tp-no', 'no', { x: tx(3) + 1.18, y: 4.58, w: 0.5, h: 0.3, fontSize: 12, bold: true, color: K.red });
    box('tp-back', titled('Hold back', 'MG ZS EV: 43.6 % flagged', { ts: 14, ds: 11.5 }), { x: tx(3) - 0.05, y: 5.05, w: 2.3, h: 0.95, fill: { color: K.redSoft }, line: { type: 'none' } });
    [['4', 'vehicles in production'], ['296', 'identifier models'], ['3,436,061', 'training frames'], ['1,130,500', 'holdout frames']].forEach(([n, l], k) => {
      const x = 0.6 + (k % 2) * 2.3, y = 3.35 + Math.floor(k / 2) * 1.4;
      text(`tps${k}`, [br(n, { fontFace: HEAD, fontSize: k < 2 ? 30 : 22, color: K.acc }), run(l, { fontSize: 12.5, color: K.mute })], { x, y, w: 2.25, h: 1.2 });
    });
  }

  slide(3, 'Live capture without a vehicle: the bench rig', 'No vehicle was available, so I built a bench rig to test live capture. Two Arduino Uno boards, each with an MCP2515 CAN module, are joined by a two wire bus at 500 kilobits per second, with a 120 ohm resistor at each end. The bridge board is connected by USB and speaks the slcan protocol that python-can understands.\n\nThe simulator sends a speed of 60 km/h every 20 milliseconds, a state of charge of 78 percent every 200 milliseconds, and, from the 35th second, a frame on 0x666, an identifier that should not exist.\n\nTo be clear: this tests the transport of live capture, from the bus to the runtime engine. It does not measure detection, because the traffic is synthetic.', { ...BK, label: 'Bench rig' });
  {
    box('rig-sim', titled('Simulator', 'Arduino Uno + MCP2515 CAN module', { ts: 16, ds: 12.5 }), { x: 0.6, y: 1.8, w: 2.95, h: 1.4, align: 'left', margin: 12 });
    line('rig-bh', 3.55, 2.4, 3.1, 0, { color: K.acc, width: 3 });
    line('rig-bl', 3.55, 2.62, 3.1, 0, { color: K.blue, width: 3 });
    text('rig-bt', 'CAN bus, 500 kbit/s', { x: 3.55, y: 1.95, w: 3.1, h: 0.3, fontSize: 12.5, color: K.ink, align: 'center' });
    text('rig-bt2', '120 Ω at both ends', { x: 3.55, y: 2.75, w: 3.1, h: 0.3, fontSize: 12, color: K.mute, align: 'center' });
    box('rig-br', titled('Bridge', 'Arduino Uno + MCP2515, speaks slcan over USB', { ts: 16, ds: 12.5 }), { x: 6.65, y: 1.8, w: 2.95, h: 1.4, align: 'left', margin: 12 });
    arrow('rig-usb', 9.62, 2.5, 0.55, 0, { color: K.acc, width: 2 });
    text('rig-usb-t', 'USB', { x: 9.6, y: 2.12, w: 0.6, h: 0.28, fontSize: 11, bold: true, color: K.mute, align: 'center' });
    box('rig-app', titled('CANvisionNative', 'python-can → runtime engine', { tc: K.acc, ts: 15, ds: 12 }), { x: 10.2, y: 1.8, w: 2.53, h: 1.4, fill: { color: K.accSoft }, line: { type: 'none' } });
    text('rf-h', 'What the simulator sends', { x: 0.6, y: 3.7, w: 6.0, h: 0.35, fontFace: HEAD, fontSize: 15, color: K.ink });
    [['0x316', 'speed, 60 km/h', 'every 20 ms', K.acc], ['0x3F9', 'state of charge, 78 %', 'every 200 ms', K.acc], ['0x666', 'should not exist', 'every 20 s, from 35 s', K.warn]].forEach(([id, m, p, c], k) => {
      const y = 4.15 + k * 0.5;
      text(`rf${k}-id`, id, { x: 0.6, y, w: 0.9, h: 0.4, fontFace: MONO, fontSize: 14, bold: true, color: c, valign: 'middle' });
      text(`rf${k}-m`, m, { x: 1.6, y, w: 2.7, h: 0.4, fontSize: 14, color: K.ink, valign: 'middle' });
      text(`rf${k}-p`, p, { x: 4.3, y, w: 2.4, h: 0.4, fontSize: 13.5, color: K.mute, valign: 'middle' });
    });
    text('rf-rate', 'About 55 frames per second', { x: 0.6, y: 5.75, w: 6.0, h: 0.35, fontSize: 13, italic: true, color: K.mute });
    box('rig-lim', [br('What it shows, and what it does not', { bold: true, color: K.warn, fontSize: 15, paraSpaceAfter: 6 }), br('It tests the transport of live capture, from the bus to the runtime engine.', { color: K.ink, paraSpaceAfter: 6 }),
      run('It does not measure detection: the traffic is synthetic and much simpler than a car\'s. No vehicle was available.', { color: K.body })],
    { x: 7.1, y: 3.7, w: 5.63, h: 2.5, fontSize: 13.5, align: 'left', valign: 'top', margin: 16, fill: { color: K.warnSoft }, line: { type: 'none' } });
  }

  slide(5, 'Why Isolation Forest?', 'Why Isolation Forest? We measured it against the two other candidates, LOF and a One Class SVM, under exactly the same conditions: same split, same features, same training rows, same threshold rule.\n\nSince the holdouts are assumed to be normal traffic, every flagged row is a false alarm. Isolation Forest flags the fewest on average, 3.2 percent against 5.1 and 6.5, and it has the lowest worst case.\n\nThis has a price: it is the slowest of the three, about 23 milliseconds per frame. We kept it because the offline analysis, the main use of the platform, needs few and even false alarms more than it needs speed.', { ...BK, label: 'Isolation Forest compared with LOF and One Class SVM' });
  {
    const cats = ['Jaguar I-PACE', 'Kia EV6', 'Nissan Leaf 2019', 'ROAD'];
    // Drawn with shapes: a chart object embeds an Excel workbook, which PowerPoint may refuse to open.
    {
      const series = [['Isolation Forest', [3.37, 2.58, 0.48, 6.39], K.acc], ['LOF', [13.09, 2.60, 1.47, 3.40], K.blue], ['One Class SVM', [13.98, 3.46, 2.04, 6.67], K.warn]];
      const X0 = 1.15, X1 = 7.75, Y0 = 2.35, Y1 = 5.75, VMAX = 16, slot = (X1 - X0) / 4, bw = 0.38;
      const yv = (v) => Y1 - (v / VMAX) * (Y1 - Y0);
      text('c-title', 'Holdout rows flagged (%), normal traffic', { x: 0.6, y: 1.75, w: 7.3, h: 0.36, fontSize: 14, color: K.ink, align: 'center' });
      for (let v = 0; v <= VMAX; v += 2) {
        line(`c-grid${v}`, X0, yv(v), X1 - X0, 0, { color: 'E5E8EC', width: 0.75 });
        text(`c-ax${v}`, String(v), { x: 0.6, y: yv(v) - 0.12, w: 0.45, h: 0.24, fontSize: 10, color: K.mute, align: 'right' });
      }
      cats.forEach((c, k) => {
        const cx = X0 + slot * (k + 0.5);
        series.forEach(([nm, vals, col], j) => {
          const x = cx + (j - 1) * (bw + 0.04) - bw / 2, v = vals[k];
          rect(`c-bar${k}${j}`, { x, y: yv(v), w: bw, h: Y1 - yv(v), round: false, fill: { color: col }, line: { type: 'none' } });
          text(`c-val${k}${j}`, v.toFixed(1), { x: x - 0.12, y: yv(v) - 0.24, w: bw + 0.24, h: 0.22, fontSize: 9, color: K.body, align: 'center' });
        });
        text(`c-cat${k}`, c, { x: cx - slot / 2, y: Y1 + 0.08, w: slot, h: 0.28, fontSize: 12, color: K.body, align: 'center' });
      });
      series.forEach(([nm, , col], j) => {
        rect(`c-lg${j}`, { x: 1.4 + j * 2.0, y: 6.24, w: 0.22, h: 0.16, round: false, fill: { color: col }, line: { type: 'none' } });
        text(`c-lg${j}t`, nm, { x: 1.7 + j * 2.0, y: 6.18, w: 1.7, h: 0.28, fontSize: 11, color: K.body });
      });
    }
    text('c-mean-h', 'Mean share flagged', { x: 8.3, y: 1.75, w: 4.4, h: 0.32, fontSize: 14, bold: true, color: K.ink });
    [['3.2 %', 'Isolation Forest', K.acc], ['5.1 %', 'LOF', K.blue], ['6.5 %', 'One Class SVM', K.warn]].forEach(([n, l, c], k) => {
      text(`c-m${k}`, [br(n, { fontFace: HEAD, fontSize: 24, color: c }), run(l, { fontSize: 11.5, color: K.mute })], { x: 8.3 + k * 1.5, y: 2.12, w: 1.45, h: 0.9 });
    });
    text('c-worst', [run('Lowest worst case: ', { bold: true, color: K.ink }), run('6.4 % for Isolation Forest, against 13.1 % and 14.0 %.')], { x: 8.3, y: 3.2, w: 4.43, h: 0.65, fontSize: 13.5 });
    text('c-price', [run('The price: it is the slowest. ', { bold: true, color: K.ink }), run('23.4 ms to score a frame against 0.97 and 0.42 ms; 138 s of training against 41 and 17 s.')], { x: 8.3, y: 4.0, w: 4.43, h: 0.95, fontSize: 13.5 });
    box('c-keep', 'We kept it: the offline analysis, the main use of the platform, needs few and even false alarms more than speed.', { x: 8.3, y: 5.15, w: 4.43, h: 1.35, fontSize: 13.5, align: 'left', margin: 14, fill: { color: K.accSoft }, line: { type: 'none' } });
    text('c-foot', 'Same split, same 9 features, same training rows (at most 5,000 per identifier), same threshold rule. No labels.', { x: 0.6, y: 6.62, w: 12.13, h: 0.3, fontSize: 11.5, italic: true, color: K.mute });
  }

  slide(5, 'Speed, live capture and automated tests', 'Three more results.\n\nSpeed: one model call costs about 24 milliseconds, so the live path processes 200 to 260 frames per second. That keeps up with the Nissan Leaf, about 100 frames per second, but not with buses that carry thousands. The offline analysis is not limited in the same way: almost half a million frames in about three minutes.\n\nLive capture on the bench rig: after 16,304 frames, a single malformed line on the serial link closed the session. Now the bad line is skipped and logged, and the link held at 55 frames per second. I also fixed old data staying on screen after unplugging the rig.\n\nAnd two automated test suites, 318 backend tests and 86 desktop tests, run after every change.', { ...BK, label: 'Speed, live capture and tests' });
  [['Speed', '≈ 24 ms', 'per model call', [['Live path: ', '200 to 260 frames/s'], ['Keeps up with ', 'the Nissan Leaf (about 100 frames/s), not with the Jaguar I-PACE (about 3,000)'], ['Offline: ', '491,969 frames in 187 s']], K.acc],
    ['Live capture on the rig', '16,304', 'frames, then one malformed serial line closed the session', [['Fixed: ', 'the bad line is skipped and logged; the link then held at about 55 frames/s'], ['Fixed: ', 'an unplugged rig kept showing old data; the link is now lost after 5 s without frames']], K.warn],
    ['Automated tests', '318 + 86', 'backend tests (pytest) and desktop tests (xUnit)', [['Run after every change: ', 'parsers, manifests, model status, scoring, unresolved frames, calibration, PDF report']], K.green]].forEach(([t, n, l, body, c], k) => {
    const x = 0.6 + k * 4.11, y = 1.7, w = 3.91;
    rect(`sp${k}`, { x, y, w, h: 4.95, fill: { color: 'FFFFFF' } });
    text(`sp${k}-t`, t, { x: x + 0.25, y: y + 0.2, w: w - 0.5, h: 0.45, fontFace: HEAD, fontSize: 17, color: K.ink });
    text(`sp${k}-n`, n, { x: x + 0.25, y: y + 0.75, w: w - 0.5, h: 0.7, fontFace: HEAD, fontSize: 32, color: c });
    text(`sp${k}-l`, l, { x: x + 0.25, y: y + 1.5, w: w - 0.5, h: 0.65, fontSize: 13, color: K.mute });
    line(`sp${k}-r`, x + 0.25, y + 2.25, w - 0.5, 0);
    text(`sp${k}-b`, body.flatMap(([a, b], i) => [run(a, { bold: true, color: K.ink }), run(b, { breakLine: i < body.length - 1, paraSpaceAfter: 8 })]), { x: x + 0.25, y: y + 2.4, w: w - 0.5, h: 2.4, fontSize: 13 });
  });

  // ---------- notes of the closing slide, animation spec, speech ----------
  const main = deck.filter((d) => !d.hidden), back = deck.filter((d) => d.hidden);
  const closing = deck.find((d) => d.title === 'Closing');
  const backupLine = '\n\nBACKUP, hidden slides for questions (in the slideshow, type the number and press Enter): ' + back.map((d) => `${deck.indexOf(d) + 1} ${d.title}`).join('; ') + '.';
  for (const d of deck) d.s.addNotes(d === closing ? d.notes + backupLine : d.notes);
  const spec = deck.map((d, i) => ({ index: i + 1, hidden: d.hidden, clicks: d.clicks.map((names) => ({ names })) })).filter((d) => d.hidden || d.clicks.length);
  fs.writeFileSync(path.join(__dirname, 'light_anim.json'), JSON.stringify({ slides: spec }, null, 1));
  await pres.writeFile({ fileName: OUT });
  console.log('wrote', OUT, deck.length, 'slides,', main.length, 'presented,', back.length, 'hidden;', spec.reduce((s, d) => s + d.clicks.length, 0), 'clicks');
  console.log(main.map((d, i) => `${i + 1}:${d.title}(${d.clicks.length})`).join('  '));
}

build().catch((e) => { console.error(e); process.exit(1); });
