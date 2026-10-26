"""Writer for draw.io (diagrams.net) files.

The figures of the report are described in figures.py with the position of each
shape; draw.io routes the connectors itself. Every figure is saved as a .drawio
file that opens and edits in draw.io, and exported to PNG by the draw.io
desktop application.
"""
from __future__ import annotations

import html
import subprocess
from pathlib import Path
from xml.sax.saxutils import quoteattr

DRAWIO = Path.home() / "AppData" / "Local" / "Programs" / "draw.io" / "draw.io.exe"

# draw.io's standard palette: (fill, stroke)
COLORS = {
    "blue":   ("#dae8fc", "#6c8ebf"),
    "green":  ("#d5e8d4", "#82b366"),
    "yellow": ("#fff2cc", "#d6b656"),
    "orange": ("#ffe6cc", "#d79b00"),
    "red":    ("#f8cecc", "#b85450"),
    "purple": ("#e1d5e7", "#9673a6"),
    "grey":   ("#f5f5f5", "#666666"),
    "white":  ("#ffffff", "#000000"),
    "black":  ("#000000", "#000000"),
}

FONT = "fontFamily=Helvetica;fontSize=12;"
EDGE = "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;fontSize=11;"


def _text(label: str) -> str:
    """Plain text with \\n line breaks, as a draw.io HTML label."""
    return html.escape(label, quote=False).replace("\n", "<br>")


def _color(color: str) -> str:
    fill, stroke = COLORS[color]
    return f"fillColor={fill};strokeColor={stroke};"


def class_height(attrs=(), methods=(), stereotype: str = "") -> int:
    """Height of a uml_class box: title, then 15 px per member and 8 px per section."""
    return 26 + (14 if stereotype else 0) + 15 * (len(attrs) + len(methods)) + 8 * sum(1 for p in (attrs, methods) if p)


class Diagram:
    def __init__(self, name: str) -> None:
        self.name = name
        self._cells: list[str] = []
        self._n = 0

    # ── low level ────────────────────────────────────────────────────────────
    def _id(self) -> str:
        self._n += 1
        return f"n{self._n}"

    def vertex(self, value: str, x: float, y: float, w: float, h: float, style: str,
               id: str | None = None) -> str:
        id = id or self._id()
        self._cells.append(
            f'<mxCell id="{id}" value={quoteattr(value)} style={quoteattr(style)} vertex="1" parent="1">'
            f'<mxGeometry x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" as="geometry"/></mxCell>')
        return id

    def edge(self, src: str | None, tgt: str | None, label: str = "", style: str = EDGE,
             exit: tuple[float, float] | None = None, entry: tuple[float, float] | None = None,
             points: list[tuple[float, float]] | None = None,
             src_pt: tuple[float, float] | None = None, tgt_pt: tuple[float, float] | None = None) -> str:
        id = self._id()
        if exit:
            style += f"exitX={exit[0]:g};exitY={exit[1]:g};exitDx=0;exitDy=0;"
        if entry:
            style += f"entryX={entry[0]:g};entryY={entry[1]:g};entryDx=0;entryDy=0;"
        ends = (f' source="{src}"' if src else "") + (f' target="{tgt}"' if tgt else "")
        geo = ""
        if src_pt:
            geo += f'<mxPoint x="{src_pt[0]:g}" y="{src_pt[1]:g}" as="sourcePoint"/>'
        if tgt_pt:
            geo += f'<mxPoint x="{tgt_pt[0]:g}" y="{tgt_pt[1]:g}" as="targetPoint"/>'
        if points:
            geo += '<Array as="points">' + "".join(f'<mxPoint x="{x:g}" y="{y:g}"/>' for x, y in points) + "</Array>"
        self._cells.append(
            f'<mxCell id="{id}" value={quoteattr(_text(label))} style={quoteattr(style)} edge="1" parent="1"{ends}>'
            f'<mxGeometry relative="1" as="geometry">{geo}</mxGeometry></mxCell>')
        return id

    # where the multiplicity of each end goes, by the direction of the line from source to
    # target: (align, verticalAlign, dx, dy) of the source label, then of the target label
    _ENDS = {
        "lr": (("left", "bottom", 6, -2), ("right", "bottom", -6, -2)),
        "rl": (("right", "bottom", -6, -2), ("left", "bottom", 6, -2)),
        "tb": (("left", "top", 6, 4), ("left", "bottom", 6, -4)),
        "bt": (("left", "bottom", 6, -4), ("left", "top", 6, 4)),
    }

    def end_labels(self, edge_id: str, source: str = "", target: str = "", way: str = "lr") -> None:
        """Multiplicities at the two ends of an association."""
        for text, x, (align, valign, dx, dy) in ((source, -1, self._ENDS[way][0]), (target, 1, self._ENDS[way][1])):
            if text:
                self._cells.append(
                    f'<mxCell id="{self._id()}" value={quoteattr(_text(text))} '
                    f'style="edgeLabel;resizable=0;html=1;align={align};verticalAlign={valign};fontSize=11;'
                    f'labelBackgroundColor=none;" vertex="1" connectable="0" parent="{edge_id}">'
                    f'<mxGeometry x="{x}" relative="1" as="geometry"><mxPoint x="{dx}" y="{dy}" as="offset"/>'
                    f'</mxGeometry></mxCell>')

    # ── shapes (x, y are the centre) ─────────────────────────────────────────
    def box(self, label: str, cx: float, cy: float, w: float = 160, h: float = 40, color: str = "blue",
            rounded: bool = True, extra: str = "", id: str | None = None) -> str:
        style = f"rounded={int(rounded)};whiteSpace=wrap;html=1;{_color(color)}{FONT}{extra}"
        return self.vertex(_text(label), cx - w / 2, cy - h / 2, w, h, style, id)

    def decision(self, label: str, cx: float, cy: float, w: float = 150, h: float = 64,
                 color: str = "yellow", id: str | None = None) -> str:
        style = f"rhombus;whiteSpace=wrap;html=1;{_color(color)}{FONT}"
        return self.vertex(_text(label), cx - w / 2, cy - h / 2, w, h, style, id)

    def merge(self, cx: float, cy: float, color: str = "yellow", id: str | None = None) -> str:
        return self.vertex("", cx - 12, cy - 12, 24, 24, f"rhombus;html=1;{_color(color)}", id)

    def start(self, cx: float, cy: float, id: str | None = None) -> str:
        return self.vertex("", cx - 12, cy - 12, 24, 24,
                           "ellipse;html=1;shape=startState;fillColor=#000000;strokeColor=#000000;", id)

    def end(self, cx: float, cy: float, id: str | None = None) -> str:
        return self.vertex("", cx - 13, cy - 13, 26, 26,
                           "ellipse;html=1;shape=endState;fillColor=#000000;strokeColor=#000000;", id)

    def lane(self, label: str, x: float, y: float, w: float, h: float, color: str = "blue") -> str:
        style = f"swimlane;html=1;startSize=30;{_color(color)}{FONT}fontStyle=1;swimlaneFillColor=#ffffff;"
        return self.vertex(_text(label), x, y, w, h, style)

    def group(self, label: str, x: float, y: float, w: float, h: float, color: str = "grey",
              extra: str = "") -> str:
        """A titled container (package, component group, node)."""
        style = (f"swimlane;html=1;startSize=28;{_color(color)}{FONT}fontStyle=1;"
                 f"swimlaneFillColor=#ffffff;rounded=0;{extra}")
        return self.vertex(_text(label), x, y, w, h, style)

    def frame(self, label: str, x: float, y: float, w: float, h: float) -> str:
        """A plain rectangle with its title at the top (use case system boundary)."""
        style = f"rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor=#666666;verticalAlign=top;fontStyle=1;{FONT}"
        return self.vertex(_text(label), x, y, w, h, style)

    def actor(self, label: str, cx: float, cy: float, id: str | None = None) -> str:
        style = f"shape=umlActor;verticalLabelPosition=bottom;verticalAlign=top;html=1;outlineConnect=0;{_color('white')}{FONT}"
        return self.vertex(_text(label), cx - 15, cy - 30, 30, 60, style, id)

    def usecase(self, label: str, cx: float, cy: float, w: float = 160, h: float = 50,
                color: str = "blue", id: str | None = None) -> str:
        style = f"ellipse;whiteSpace=wrap;html=1;{_color(color)}{FONT}"
        return self.vertex(_text(label), cx - w / 2, cy - h / 2, w, h, style, id)

    def cylinder(self, label: str, cx: float, cy: float, w: float = 120, h: float = 70,
                 color: str = "grey", id: str | None = None) -> str:
        style = f"shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=12;{_color(color)}{FONT}"
        return self.vertex(_text(label), cx - w / 2, cy - h / 2, w, h, style, id)

    def cloud(self, label: str, cx: float, cy: float, w: float = 150, h: float = 80,
              color: str = "grey", id: str | None = None) -> str:
        style = f"ellipse;shape=cloud;whiteSpace=wrap;html=1;{_color(color)}{FONT}"
        return self.vertex(_text(label), cx - w / 2, cy - h / 2, w, h, style, id)

    def cube(self, label: str, cx: float, cy: float, w: float = 160, h: float = 60,
             color: str = "grey", id: str | None = None) -> str:
        style = (f"shape=cube;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;darkOpacity=0.05;"
                 f"darkOpacity2=0.1;size=10;{_color(color)}{FONT}")
        return self.vertex(_text(label), cx - w / 2, cy - h / 2, w, h, style, id)

    def folder(self, label: str, cx: float, cy: float, w: float = 150, h: float = 60,
               color: str = "yellow", id: str | None = None) -> str:
        style = (f"shape=folder;fontStyle=0;spacingTop=10;tabWidth=40;tabHeight=14;tabPosition=left;"
                 f"whiteSpace=wrap;html=1;{_color(color)}{FONT}")
        return self.vertex(_text(label), cx - w / 2, cy - h / 2, w, h, style, id)

    def doc(self, label: str, cx: float, cy: float, w: float = 160, h: float = 50,
            color: str = "yellow", id: str | None = None) -> str:
        """A file (sheet with a folded corner)."""
        style = (f"shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;size=14;"
                 f"{_color(color)}{FONT}")
        return self.vertex(_text(label), cx - w / 2, cy - h / 2, w, h, style, id)

    def note(self, label: str, x: float, y: float, w: float, h: float, id: str | None = None) -> str:
        style = (f"shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;darkOpacity=0.05;size=12;"
                 f"align=left;spacingLeft=6;{_color('yellow')}{FONT}")
        return self.vertex(_text(label), x, y, w, h, style, id)

    def text(self, label: str, x: float, y: float, w: float, h: float, align: str = "left",
             extra: str = "") -> str:
        style = f"text;html=1;strokeColor=none;fillColor=none;align={align};verticalAlign=middle;whiteSpace=wrap;{FONT}{extra}"
        return self.vertex(_text(label), x, y, w, h, style)

    def bar(self, cx: float, cy: float, w: float, id: str | None = None) -> str:
        """Fork or join bar of an activity diagram."""
        return self.vertex("", cx - w / 2, cy - 3, w, 6, f"html=1;points=[];{_color('black')}", id)

    def uml_class(self, name: str, x: float, y: float, w: float, attrs: list[str] = (),
                  methods: list[str] = (), color: str = "blue", stereotype: str = "",
                  italic: bool = False, id: str | None = None) -> str:
        head = (f"<i>«{html.escape(stereotype)}»</i><br>" if stereotype else "")
        title = f"<i>{html.escape(name)}</i>" if italic else html.escape(name)
        body = f'<p style="margin:0px;margin-top:4px;text-align:center;">{head}<b>{title}</b></p>'
        for part in (attrs, methods):
            if part:
                body += '<hr size="1" style="border-style:solid;">'
                body += ('<p style="margin:0px;margin-left:6px;">'
                         + "<br>".join(html.escape(m) for m in part) + "</p>")
        h = class_height(attrs, methods, stereotype)
        style = f"verticalAlign=top;align=left;overflow=fill;html=1;whiteSpace=wrap;{_color(color)}{FONT}"
        return self.vertex(body, x, y, w, h, style, id)

    # ── output ───────────────────────────────────────────────────────────────
    def xml(self) -> str:
        cells = "".join(self._cells)
        return ('<mxfile host="drawio" agent="draw.io"><diagram name="' + self.name + '" id="' + self.name + '">'
                '<mxGraphModel dx="1200" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" '
                'arrows="1" fold="1" page="0" pageScale="1" pageWidth="1169" pageHeight="827" math="0" shadow="0">'
                '<root><mxCell id="0"/><mxCell id="1" parent="0"/>' + cells + "</root></mxGraphModel></diagram></mxfile>")

    def save(self, folder: Path) -> Path:
        path = folder / f"{self.name}.drawio"
        path.write_text(self.xml(), encoding="utf-8")
        return path


# ── edge styles ─────────────────────────────────────────────────────────────
FLOW = EDGE + "endArrow=block;endFill=1;"
STRAIGHT = "html=1;rounded=0;fontSize=11;endArrow=block;endFill=1;"
ASSOC = "html=1;rounded=0;fontSize=11;endArrow=none;"
DASHED_OPEN = "html=1;rounded=0;fontSize=11;endArrow=open;endFill=0;dashed=1;endSize=10;"
GENERALIZE = EDGE + "endArrow=block;endFill=0;endSize=12;"
COMPOSE = EDGE + "startArrow=diamondThin;startFill=1;startSize=14;endArrow=none;"
AGGREGATE = EDGE + "startArrow=diamondThin;startFill=0;startSize=14;endArrow=none;"
DEPEND = EDGE + "endArrow=open;endFill=0;dashed=1;endSize=10;"


class Sequence:
    """A UML sequence diagram laid out on fixed columns and rows."""

    # robustness stereotypes drawn with the UML icons of draw.io: (participant shape, icon width)
    STEREO = {"boundary": ("umlBoundary", 50), "control": ("umlControl", 40), "entity": ("umlEntity", 40)}

    def __init__(self, d: Diagram, top: float = 20, head: float = 40, numbered: bool = False) -> None:
        self.d, self.top, self.head = d, top, head
        self.x: dict[str, float] = {}
        self.kind: dict[str, tuple[str, str, float, str]] = {}
        self.acts: list[list] = []
        self.numbered, self.n = numbered, 0

    def participant(self, key: str, label: str, cx: float, w: float = 150, color: str = "blue",
                    actor: bool = False, stereo: str = "") -> None:
        """stereo: "boundary", "control" or "entity" draws the robustness icon and the stereotype."""
        self.x[key] = cx
        self.kind[key] = (label, "actor" if actor else color, w, stereo)

    def _label(self, label: str) -> str:
        if not self.numbered:
            return label
        self.n += 1
        return f"{self.n}: {label}"

    def draw_lifelines(self, bottom: float) -> None:
        for key, cx in self.x.items():
            label, kind, w, stereo = self.kind[key]
            h = bottom - self.top
            if kind == "actor":
                style = ("shape=umlLifeline;participant=umlActor;perimeter=lifelinePerimeter;whiteSpace=wrap;html=1;"
                         "container=1;collapsible=0;recursiveResize=0;verticalAlign=top;spacingTop=36;"
                         f"labelBackgroundColor=#ffffff;outlineConnect=0;size=40;{FONT}")
                self.d.vertex(_text(label), cx - 10, self.top, 20, h, style)
            elif stereo:
                shape, iw = self.STEREO[stereo]
                style = (f"shape=umlLifeline;participant={shape};perimeter=lifelinePerimeter;whiteSpace=nowrap;html=1;"
                         "container=1;collapsible=0;recursiveResize=0;verticalAlign=top;spacingTop=40;"
                         f"labelBackgroundColor=#ffffff;outlineConnect=0;size=40;{_color(kind)}{FONT}")
                self.d.vertex(_text(f"«{stereo}»\n{label}"), cx - iw / 2, self.top, iw, h, style)
            else:
                style = ("shape=umlLifeline;perimeter=lifelinePerimeter;whiteSpace=wrap;html=1;container=1;"
                         "collapsible=0;recursiveResize=0;outlineConnect=0;"
                         f"size={self.head:g};{_color(kind)}{FONT}")
                self.d.vertex(_text(label), cx - w / 2, self.top, w, h, style)

    def activate(self, key: str, y0: float, y1: float) -> None:
        self.acts.append([key, y0, y1])

    def draw_activations(self) -> None:
        for key, y0, y1 in self.acts:
            self.d.vertex("", self.x[key] - 5, y0, 10, y1 - y0,
                          f"html=1;points=[];perimeter=orthogonalPerimeter;{_color('white')}")

    def _active(self, key: str, y: float) -> bool:
        return any(k == key and y0 <= y <= y1 for k, y0, y1 in self.acts)

    def msg(self, a: str, b: str, y: float, label: str, reply: bool = False, asyn: bool = False) -> None:
        """A synchronous call (filled arrow), an asynchronous message (asyn: open arrow, solid line)
        or a reply (dashed line, open arrow)."""
        xa, xb = self.x[a], self.x[b]
        right = xb > xa
        xa += (5 if right else -5) if self._active(a, y) else 0
        xb += (-5 if right else 5) if self._active(b, y) else 0
        if reply:
            style = "html=1;verticalAlign=bottom;endArrow=open;dashed=1;endSize=8;rounded=0;fontSize=11;"
        elif asyn:
            style = "html=1;verticalAlign=bottom;endArrow=open;endSize=8;rounded=0;fontSize=11;"
        else:
            style = "html=1;verticalAlign=bottom;endArrow=block;endFill=1;rounded=0;fontSize=11;"
        self.d.edge(None, None, self._label(label), style, src_pt=(xa, y), tgt_pt=(xb, y))

    def self_msg(self, a: str, y: float, label: str, h: float = 24) -> None:
        x = self.x[a] + (5 if self._active(a, y) else 0)
        style = ("html=1;align=left;spacingLeft=4;endArrow=block;endFill=1;rounded=0;fontSize=11;"
                 "labelBackgroundColor=#ffffff;")
        self.d.edge(None, None, self._label(label), style, src_pt=(x, y), tgt_pt=(x, y + h),
                    points=[(x + 36, y), (x + 36, y + h)])

    def fragment(self, kind: str, guard: str, x0: float, y0: float, x1: float, y1: float,
                 splits: list[tuple[float, str]] = ()) -> None:
        self.d.vertex(kind, x0, y0, x1 - x0, y1 - y0,
                      f"shape=umlFrame;whiteSpace=wrap;html=1;pointerEvents=0;width=46;height=20;"
                      f"fillColor=none;swimlaneFillColor=none;{FONT}fontStyle=1;")
        guard_style = "fontStyle=1;labelBackgroundColor=#ffffff;"

        def width(text: str) -> float:   # bold 12 px Helvetica, about 7 px a character
            return 7 * len(text) + 12

        self.d.text(f"[{guard}]", x0 + 52, y0, width(guard), 20, extra=guard_style)
        for ys, g in splits:
            self.d.edge(None, None, "", "html=1;endArrow=none;dashed=1;rounded=0;",
                        src_pt=(x0, ys), tgt_pt=(x1, ys))
            self.d.text(f"[{g}]", x0 + 6, ys, width(g), 20, extra=guard_style)


def export(path: Path, scale: float = 2) -> Path:
    png = path.with_suffix(".png")
    subprocess.run([str(DRAWIO), "-x", "-f", "png", "-s", str(scale), "-b", "12",
                    "-o", str(png), str(path)], check=True, capture_output=True, timeout=180)
    return png
