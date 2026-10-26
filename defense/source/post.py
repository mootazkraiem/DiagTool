# Post-process the deck written by build.js:
#   1. a Morph transition (by object) on every slide,
#   2. the dark colour map on the master (bg1=dk1, tx1=lt1, bg2=dk2, tx2=lt2),
#   3. the slide animations described in anim.json (written by build.js).
# Usage: python post.py deck.pptx [anim.json] [morph_ms]
import json, os, re, sys, zipfile

src = sys.argv[1]
anim_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'anim.json')
dur = int(sys.argv[3]) if len(sys.argv) > 3 else 1200
SLIDE_W, SLIDE_H = 13.333, 7.5  # inches, LAYOUT_WIDE

TRANS = ('<mc:AlternateContent xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">'
         '<mc:Choice xmlns:p159="http://schemas.microsoft.com/office/powerpoint/2015/09/main" '
         'xmlns:p14="http://schemas.microsoft.com/office/powerpoint/2010/main" Requires="p159">'
         '<p:transition spd="slow" p14:dur="%d"><p159:morph option="byObject"/></p:transition></mc:Choice>'
         '<mc:Fallback><p:transition spd="slow"><p:fade/></p:transition></mc:Fallback></mc:AlternateContent>') % dur
CLRMAP = ('<p:clrMap bg1="dk1" tx1="lt1" bg2="dk2" tx2="lt2" accent1="accent1" accent2="accent2" '
          'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>')

anims, hidden = {}, set()
if os.path.exists(anim_path):
    raw = json.load(open(anim_path, encoding='utf8'))
    hidden = set(raw.pop('_hidden', []))
    anims = {int(k): v for k, v in raw.items()}


def shape_ids(xml):
    """name -> (spid, element tag) for every shape of the slide."""
    out = {}
    for m in re.finditer(r'<p:(sp|pic|cxnSp)>\s*<p:nv\w+Pr>\s*<p:cNvPr\b([^>]*)>', xml):
        attrs = m.group(2)
        sid = re.search(r'\bid="(\d+)"', attrs).group(1)
        name = re.search(r'\bname="([^"]*)"', attrs).group(1)
        out[name] = (sid, m.group(1))
    return out


class Ids:
    def __init__(self, start):
        self.n = start

    def __call__(self):
        self.n += 1
        return self.n


def tgt(spid):
    return f'<p:tgtEl><p:spTgt spid="{spid}"/></p:tgtEl>'


def show(ids, spid):
    return (f'<p:set><p:cBhvr><p:cTn id="{ids()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst></p:cTn>'
            f'{tgt(spid)}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
            f'<p:to><p:strVal val="visible"/></p:to></p:set>')


def effect(ids, e, spid, node_type):
    kind = e['type']
    delay = int(e.get('delay', 0))
    d = int(e.get('dur', 500))
    rep = e.get('repeat')
    rep_attr = '' if not rep else (' repeatCount="indefinite"' if rep is True else f' repeatCount="{int(rep) * 1000}"')
    head_id = ids()
    if kind == 'fade':
        preset = 'presetID="10" presetClass="entr" presetSubtype="0"'
        body = show(ids, spid) + (f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{ids()}" dur="{d}"/>'
                                  f'{tgt(spid)}</p:cBhvr></p:animEffect>')
    elif kind == 'flyfrom':  # entrance: appear at an offset (inches), wait, then glide to the layout position
        preset = 'presetID="2" presetClass="entr" presetSubtype="0"'
        hold = int(e.get('hold', 0) * 100000)

        def glide(attr, off):
            start = f'#{attr}{"+" if off >= 0 else "-"}{abs(off):.5f}'
            tavs = f'<p:tav tm="0"><p:val><p:strVal val="{start}"/></p:val></p:tav>'
            if hold:
                tavs += f'<p:tav tm="{hold}"><p:val><p:strVal val="{start}"/></p:val></p:tav>'
            tavs += f'<p:tav tm="100000"><p:val><p:strVal val="#{attr}"/></p:val></p:tav>'
            return (f'<p:anim calcmode="lin" valueType="num"><p:cBhvr additive="base"><p:cTn id="{ids()}" dur="{d}" fill="hold"/>'
                    f'{tgt(spid)}<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr><p:tavLst>{tavs}</p:tavLst></p:anim>')
        body = (show(ids, spid) + glide('ppt_x', e['dx'] / SLIDE_W) + glide('ppt_y', e['dy'] / SLIDE_H) +
                f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{ids()}" dur="250"/>{tgt(spid)}</p:cBhvr></p:animEffect>')
    elif kind == 'fadeout':  # exit: fade, then hidden
        preset = 'presetID="10" presetClass="exit" presetSubtype="0"'
        body = (f'<p:animEffect transition="out" filter="fade"><p:cBhvr><p:cTn id="{ids()}" dur="{d}"/>{tgt(spid)}</p:cBhvr></p:animEffect>'
                f'<p:set><p:cBhvr><p:cTn id="{ids()}" dur="1" fill="hold"><p:stCondLst><p:cond delay="{d - 1}"/></p:stCondLst></p:cTn>'
                f'{tgt(spid)}<p:attrNameLst><p:attrName>style.visibility</p:attrName></p:attrNameLst></p:cBhvr>'
                f'<p:to><p:strVal val="hidden"/></p:to></p:set>')
    elif kind == 'pop':  # zoom in from the centre, with a fade
        preset = 'presetID="53" presetClass="entr" presetSubtype="16"'

        def grow(attr):
            return (f'<p:anim calcmode="lin" valueType="num"><p:cBhvr><p:cTn id="{ids()}" dur="{d}" fill="hold"/>{tgt(spid)}'
                    f'<p:attrNameLst><p:attrName>{attr}</p:attrName></p:attrNameLst></p:cBhvr><p:tavLst>'
                    f'<p:tav tm="0"><p:val><p:fltVal val="0"/></p:val></p:tav>'
                    f'<p:tav tm="100000"><p:val><p:strVal val="#{attr}"/></p:val></p:tav></p:tavLst></p:anim>')
        body = (show(ids, spid) + grow('ppt_w') + grow('ppt_h') +
                f'<p:animEffect transition="in" filter="fade"><p:cBhvr><p:cTn id="{ids()}" dur="{d}"/>{tgt(spid)}</p:cBhvr></p:animEffect>')
    elif kind == 'wipe':
        sub = {'down': 1, 'left': 2, 'up': 4, 'right': 8}[e['dir']]
        preset = f'presetID="22" presetClass="entr" presetSubtype="{sub}"'
        body = show(ids, spid) + (f'<p:animEffect transition="in" filter="wipe({e["dir"]})"><p:cBhvr><p:cTn id="{ids()}" dur="{d}"/>'
                                  f'{tgt(spid)}</p:cBhvr></p:animEffect>')
    elif kind == 'motion':  # straight line at constant speed; offsets in inches
        preset = 'presetID="0" presetClass="path" presetSubtype="0"'
        # either a ready path (slide fractions, relative to the start point) or a straight offset in inches
        path = e.get('path') or f"M 0 0 L {e['dx'] / SLIDE_W:.5f} {e['dy'] / SLIDE_H:.5f} E"
        body = (f'<p:animMotion origin="layout" path="{path}" pathEditMode="relative">'
                f'<p:cBhvr><p:cTn id="{ids()}" dur="{d}" fill="hold"/>{tgt(spid)}'
                f'<p:attrNameLst><p:attrName>ppt_x</p:attrName><p:attrName>ppt_y</p:attrName></p:attrNameLst></p:cBhvr></p:animMotion>')
    elif kind == 'spin':  # full turn at constant speed, around the shape centre
        preset = 'presetID="8" presetClass="emph" presetSubtype="0"'
        body = (f'<p:animRot by="21600000"><p:cBhvr><p:cTn id="{ids()}" dur="{d}" fill="hold"/>{tgt(spid)}'
                f'<p:attrNameLst><p:attrName>r</p:attrName></p:attrNameLst></p:cBhvr></p:animRot>')
    elif kind == 'pulse':  # grow, then shrink back
        preset = 'presetID="6" presetClass="emph" presetSubtype="0"'
        s = int(e.get('scale', 1.5) * 100000)
        body = (f'<p:animScale><p:cBhvr><p:cTn id="{ids()}" dur="{d}" autoRev="1" fill="hold"/>{tgt(spid)}</p:cBhvr>'
                f'<p:by x="{s}" y="{s}"/></p:animScale>')
    else:
        raise ValueError(kind)
    return (f'<p:par><p:cTn id="{head_id}" {preset}{rep_attr} fill="hold" grpId="0" nodeType="{node_type}">'
            f'<p:stCondLst><p:cond delay="{delay}"/></p:stCondLst><p:childTnLst>{body}</p:childTnLst></p:cTn></p:par>')


def timing(groups, names):
    ids = Ids(2)  # 1 = root, 2 = main sequence
    pars, built = [], []
    for g in groups:
        outer, inner = ids(), ids()
        auto = g['trigger'] == 'auto'
        cond = '<p:cond delay="indefinite"/>' + ('<p:cond evt="onBegin" delay="0"><p:tn val="2"/></p:cond>' if auto else '')
        effs = []
        for i, e in enumerate(g['effects']):
            spid, tag = names[e['name']]
            first = 'afterEffect' if auto else 'clickEffect'
            effs.append(effect(ids, e, spid, first if i == 0 else 'withEffect'))
            if tag == 'sp' and spid not in built:
                built.append(spid)
        pars.append(f'<p:par><p:cTn id="{outer}" fill="hold"><p:stCondLst>{cond}</p:stCondLst><p:childTnLst>'
                    f'<p:par><p:cTn id="{inner}" fill="hold"><p:stCondLst><p:cond delay="0"/></p:stCondLst>'
                    f'<p:childTnLst>{"".join(effs)}</p:childTnLst></p:cTn></p:par></p:childTnLst></p:cTn></p:par>')
    bld = ''.join(f'<p:bldP spid="{s}" grpId="0" animBg="1"/>' for s in built)
    return ('<p:timing><p:tnLst><p:par><p:cTn id="1" dur="indefinite" restart="never" nodeType="tmRoot"><p:childTnLst>'
            '<p:seq concurrent="1" nextAc="seek"><p:cTn id="2" dur="indefinite" nodeType="mainSeq"><p:childTnLst>'
            + ''.join(pars) +
            '</p:childTnLst></p:cTn><p:prevCondLst><p:cond evt="onPrev" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:prevCondLst>'
            '<p:nextCondLst><p:cond evt="onNext" delay="0"><p:tgtEl><p:sldTgt/></p:tgtEl></p:cond></p:nextCondLst></p:seq>'
            '</p:childTnLst></p:cTn></p:par></p:tnLst>' + (f'<p:bldLst>{bld}</p:bldLst>' if bld else '') + '</p:timing>')


tmp = src + '.tmp'
zin = zipfile.ZipFile(src)
zout = zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED)
n_sl = n_m = n_an = 0
for item in zin.infolist():
    data = zin.read(item.filename)
    name = item.filename
    m = re.fullmatch(r'ppt/slides/slide(\d+)\.xml', name)
    if m:
        x = data.decode('utf8')
        assert '<p:transition' not in x and '<p:timing' not in x and '</p:clrMapOvr>' in x, name
        extra = TRANS
        num = int(m.group(1))
        if num in anims:
            extra += timing(anims[num], shape_ids(x))
            n_an += 1
        x = x.replace('</p:clrMapOvr>', '</p:clrMapOvr>' + extra, 1)
        if num in hidden:  # backup slide: skipped by the slideshow
            x = x.replace('<p:sld ', '<p:sld show="0" ', 1)
        data = x.encode('utf8')
        n_sl += 1
    elif re.fullmatch(r'ppt/slideMasters/slideMaster\d+\.xml', name):
        x = data.decode('utf8')
        x, k = re.subn(r'<p:clrMap\b[^>]*/>', CLRMAP, x)
        assert k == 1, name
        data = x.encode('utf8')
        n_m += 1
    zout.writestr(item, data)
zout.close()
zin.close()
os.replace(tmp, src)
print(f'morph on {n_sl} slides, animations on {n_an} slides, dark clrMap on {n_m} master(s)')
