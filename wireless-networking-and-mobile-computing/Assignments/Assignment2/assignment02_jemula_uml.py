"""Generate a UML diagram from Jemula's Java kernel sources.

Install dependencies with ``python -m pip install graphviz svgwrite tree-sitter-language-pack``.
Graphviz's ``dot`` executable must also be installed and available on PATH.
Run this file to write ``jemula_class_diagram.svg`` next to the script.
"""

from __future__ import annotations

import argparse
import html
import math
import re
from dataclasses import dataclass
from pathlib import Path

import svgwrite
from graphviz import Digraph
from tree_sitter_language_pack import get_parser


BACKGROUND = "#f3f5f2"
INK = "#1c2b32"
MUTED = "#506168"
LINE = "#62787d"
ACCENT = "#26756f"
CLASS_TYPES = {
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
}
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass
class FieldInfo:
    name: str
    type_name: str
    visibility: str
    is_static: bool

    def label(self) -> str:
        marker = {"public": "+", "protected": "#", "private": "-"}.get(self.visibility, "~")
        static_marker = " {static}" if self.is_static else ""
        return f"{marker} {self.name}: {self.type_name}{static_marker}"


@dataclass
class ClassInfo:
    name: str
    kind: str
    parent: str | None
    fields: list[FieldInfo]


def find_source_dir() -> Path:
    relative_path = Path(
        "notebooks/01 Jemula/jemula-project/simulator/kernel/src/kernel"
    )
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative_path
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "Could not find notebooks/01 Jemula/jemula-project/simulator/kernel/src/kernel "
        "relative to this script. Pass --source-dir to specify it."
    )


def node_text(node) -> str:
    text = node.text
    return text.decode("utf-8") if text is not None else ""


def parse_type_name(node) -> str | None:
    if node is None:
        return None
    identifiers = IDENTIFIER_PATTERN.findall(node_text(node))
    ignored = {"extends", "implements", "super"}
    names = [identifier for identifier in identifiers if identifier not in ignored]
    return names[-1] if names else None


def parse_field(field_node) -> list[FieldInfo]:
    type_node = field_node.child_by_field_name("type")
    if type_node is None:
        return []

    type_name = node_text(type_node).strip()
    modifiers_node = field_node.child_by_field_name("modifiers")
    modifiers = node_text(modifiers_node) if modifiers_node else ""
    visibility = next(
        (value for value in ("public", "protected", "private") if value in modifiers),
        "package",
    )
    is_static = "static" in modifiers.split()

    fields = []
    for child in field_node.named_children:
        if child.type != "variable_declarator":
            continue
        name_node = child.child_by_field_name("name")
        if name_node is not None:
            fields.append(
                FieldInfo(node_text(name_node), type_name, visibility, is_static)
            )
    return fields


def parse_sources(source_dir: Path) -> list[ClassInfo]:
    parser = get_parser("java")
    classes = []
    for source_path in sorted(source_dir.glob("*.java")):
        tree = parser.parse(source_path.read_bytes())
        if tree.root_node.has_error:
            raise SyntaxError(f"Could not parse Java source: {source_path}")

        for declaration in tree.root_node.named_children:
            if declaration.type not in CLASS_TYPES:
                continue
            name_node = declaration.child_by_field_name("name")
            body_node = declaration.child_by_field_name("body")
            if name_node is None or body_node is None:
                continue

            fields = [
                field
                for member in body_node.named_children
                if member.type == "field_declaration"
                for field in parse_field(member)
            ]
            classes.append(
                ClassInfo(
                    name=node_text(name_node),
                    kind=declaration.type.removesuffix("_declaration"),
                    parent=parse_type_name(declaration.child_by_field_name("superclass")),
                    fields=fields,
                )
            )

    if not classes:
        raise ValueError(f"No Java types found in {source_dir}")
    return classes


def inheritance_depth(class_info: ClassInfo, by_name: dict[str, ClassInfo]) -> int:
    depth = 0
    parent = class_info.parent
    visited = {class_info.name}
    while parent in by_name and parent not in visited:
        visited.add(parent)
        depth += 1
        parent = by_name[parent].parent
    return depth


def add_class(
    drawing: svgwrite.Drawing,
    info: ClassInfo,
    position: tuple[float, float],
    size: tuple[float, float],
) -> None:
    x, y = position
    width, height = size
    drawing.add(
        drawing.rect(
            insert=(x, y),
            size=(width, height),
            rx=8,
            fill="#ffffff",
            stroke="#c6d2d0",
            stroke_width=1.5,
        )
    )
    drawing.add(drawing.rect(insert=(x, y), size=(width, 7), rx=4, fill=ACCENT))
    drawing.add(
        drawing.text(
            f"kernel :: {info.kind}",
            insert=(x + 16, y + 30),
            font_family="Segoe UI, Arial, sans-serif",
            font_size=11,
            fill=ACCENT,
        )
    )
    drawing.add(
        drawing.text(
            info.name,
            insert=(x + 16, y + 55),
            font_family="Segoe UI, Arial, sans-serif",
            font_size=17,
            font_weight="bold",
            fill=INK,
        )
    )
    drawing.add(
        drawing.line(
            start=(x, y + 68),
            end=(x + width, y + 68),
            stroke="#dbe3e1",
            stroke_width=1,
        )
    )

    shown_fields = info.fields[:6]
    for index, field in enumerate(shown_fields):
        label = field.label()
        if len(label) > 41:
            label = f"{label[:38]}..."
        drawing.add(
            drawing.text(
                label,
                insert=(x + 16, y + 91 + index * 19),
                font_family="Consolas, monospace",
                font_size=11,
                fill=MUTED,
            )
        )
    if len(info.fields) > len(shown_fields):
        drawing.add(
            drawing.text(
                f"... +{len(info.fields) - len(shown_fields)} fields",
                insert=(x + 16, y + 91 + len(shown_fields) * 19),
                font_family="Segoe UI, Arial, sans-serif",
                font_size=11,
                fill=MUTED,
            )
        )
    if not info.fields:
        drawing.add(
            drawing.text(
                "(no fields)",
                insert=(x + 16, y + 92),
                font_family="Segoe UI, Arial, sans-serif",
                font_size=12,
                fill=MUTED,
            )
        )


def rectangle_edge(
    center: tuple[float, float],
    toward: tuple[float, float],
    size: tuple[float, float],
) -> tuple[float, float]:
    dx = toward[0] - center[0]
    dy = toward[1] - center[1]
    if dx == 0 and dy == 0:
        return center
    scales = []
    if dx:
        scales.append((size[0] / 2) / abs(dx))
    if dy:
        scales.append((size[1] / 2) / abs(dy))
    scale = min(scales)
    return center[0] + dx * scale, center[1] + dy * scale


def add_inheritance_marker(
    drawing: svgwrite.Drawing,
    child_center: tuple[float, float],
    parent_center: tuple[float, float],
    parent_size: tuple[float, float],
) -> None:
    tip = rectangle_edge(parent_center, child_center, parent_size)
    dx = parent_center[0] - child_center[0]
    dy = parent_center[1] - child_center[1]
    length = math.hypot(dx, dy)
    if not length:
        return
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    base_x, base_y = tip[0] - ux * 13, tip[1] - uy * 13
    drawing.add(
        drawing.polygon(
            points=[
                tip,
                (base_x + px * 7, base_y + py * 7),
                (base_x - px * 7, base_y - py * 7),
            ],
            fill=BACKGROUND,
            stroke=LINE,
            stroke_width=1.5,
        )
    )


def _generate_diagram_svgwrite(
    classes: list[ClassInfo], source_dir: Path, output_path: Path
) -> Path:
    by_name = {class_info.name: class_info for class_info in classes}
    classes.sort(key=lambda item: (inheritance_depth(item, by_name), item.name))

    class_width = 310
    class_height = 245
    margin_x = 45
    margin_y = 130
    gap_x = 48
    gap_y = 45
    columns = min(4, len(classes))
    rows = math.ceil(len(classes) / columns)
    width = margin_x * 2 + columns * class_width + (columns - 1) * gap_x
    height = margin_y + rows * class_height + (rows - 1) * gap_y + 55

    positions = {
        class_info.name: (
            margin_x + (index % columns) * (class_width + gap_x),
            margin_y + (index // columns) * (class_height + gap_y),
        )
        for index, class_info in enumerate(classes)
    }
    centers = {
        name: (x + class_width / 2, y + class_height / 2)
        for name, (x, y) in positions.items()
    }

    drawing = svgwrite.Drawing(
        str(output_path),
        size=(f"{width}px", f"{height}px"),
        viewBox=f"0 0 {width} {height}",
    )
    drawing.add(drawing.rect(insert=(0, 0), size=(width, height), fill=BACKGROUND))
    drawing.add(
        drawing.text(
            "Jemula++ Kernel Class Diagram",
            insert=(margin_x, 52),
            font_family="Segoe UI, Arial, sans-serif",
            font_size=29,
            font_weight="bold",
            fill=INK,
        )
    )
    drawing.add(
        drawing.text(
            f"Generated from {source_dir}",
            insert=(margin_x + 2, 80),
            font_family="Segoe UI, Arial, sans-serif",
            font_size=12,
            fill=MUTED,
        )
    )

    inheritance_edges = []
    association_edges = set()
    class_names = set(by_name)
    for class_info in classes:
        if class_info.parent in class_names:
            inheritance_edges.append((class_info.name, class_info.parent))
        for field in class_info.fields:
            referenced_types = set(IDENTIFIER_PATTERN.findall(field.type_name)) & class_names
            for target in referenced_types:
                if target != class_info.name:
                    association_edges.add((class_info.name, target))

    for source, target in sorted(association_edges):
        start = rectangle_edge(centers[source], centers[target], (class_width, class_height))
        end = rectangle_edge(centers[target], centers[source], (class_width, class_height))
        drawing.add(
            drawing.line(start=start, end=end, stroke="#91a5a4", stroke_width=1.5)
        )

    for child, parent in inheritance_edges:
        start = rectangle_edge(centers[child], centers[parent], (class_width, class_height))
        end = rectangle_edge(centers[parent], centers[child], (class_width, class_height))
        drawing.add(drawing.line(start=start, end=end, stroke=LINE, stroke_width=2))

    for class_info in classes:
        add_class(
            drawing,
            class_info,
            positions[class_info.name],
            (class_width, class_height),
        )

    for child, parent in inheritance_edges:
        add_inheritance_marker(
            drawing,
            centers[child],
            centers[parent],
            (class_width, class_height),
        )

    legend_y = height - 24
    drawing.add(
        drawing.line(
            start=(margin_x, legend_y - 4),
            end=(margin_x + 36, legend_y - 4),
            stroke="#91a5a4",
            stroke_width=1.5,
        )
    )
    drawing.add(
        drawing.text(
            "field-type association",
            insert=(margin_x + 44, legend_y),
            font_family="Segoe UI, Arial, sans-serif",
            font_size=11,
            fill=MUTED,
        )
    )
    drawing.add(
        drawing.text(
            "hollow triangle = extends",
            insert=(margin_x + 220, legend_y),
            font_family="Segoe UI, Arial, sans-serif",
            font_size=11,
            fill=MUTED,
        )
    )
    drawing.save(pretty=True)
    return output_path


def graphviz_class_label(class_info: ClassInfo) -> str:
    field_rows = []
    for field in class_info.fields[:7]:
        field_rows.append(
            '<TR><TD ALIGN="LEFT"><FONT FACE="Consolas" POINT-SIZE="10">'
            f"{html.escape(field.label())}</FONT></TD></TR>"
        )
    if len(class_info.fields) > 7:
        field_rows.append(
            '<TR><TD ALIGN="LEFT"><FONT FACE="Segoe UI" POINT-SIZE="9" COLOR="#506168">'
            f"... +{len(class_info.fields) - 7} fields</FONT></TD></TR>"
        )
    if not field_rows:
        field_rows.append(
            '<TR><TD ALIGN="LEFT"><FONT FACE="Segoe UI" POINT-SIZE="10">(no fields)</FONT></TD></TR>'
        )

    return (
        '<<TABLE BORDER="1" COLOR="#c6d2d0" CELLBORDER="0" CELLSPACING="0" '
        'CELLPADDING="6" BGCOLOR="#ffffff">'
        '<TR><TD ALIGN="LEFT" BGCOLOR="#e5f0ed">'
        f'<FONT FACE="Segoe UI" POINT-SIZE="9" COLOR="#26756f">kernel :: {html.escape(class_info.kind)}</FONT>'
        "</TD></TR>"
        '<TR><TD ALIGN="LEFT"><FONT FACE="Segoe UI" POINT-SIZE="14"><B>'
        f"{html.escape(class_info.name)}</B></FONT></TD></TR>"
        '<HR COLOR="#dbe3e1"/>'
        f"{''.join(field_rows)}"
        "</TABLE>>"
    )


def generate_graphviz_diagram(
    classes: list[ClassInfo], source_dir: Path, output_path: Path
) -> Path:
    graph = Digraph("JemulaKernel", format="svg", engine="dot")
    graph.attr(
        "graph",
        rankdir="BT",
        bgcolor="#f3f5f2",
        pad="0.35",
        nodesep="0.55",
        ranksep="0.8",
        splines="ortho",
        labelloc="t",
        label=f"Jemula++ Kernel Class Diagram\\nGenerated from {source_dir}",
        fontname="Segoe UI",
        fontsize="20",
        fontcolor="#1c2b32",
    )
    graph.attr("node", shape="plain", margin="0")
    graph.attr("edge", fontname="Segoe UI", fontsize="9", color="#718785")

    class_names = {class_info.name for class_info in classes}
    for class_info in classes:
        graph.node(class_info.name, label=graphviz_class_label(class_info))

    association_labels: dict[tuple[str, str], set[str]] = {}
    for class_info in classes:
        if class_info.parent in class_names:
            graph.edge(
                class_info.name,
                class_info.parent,
                arrowhead="empty",
                color="#52666d",
                penwidth="1.5",
            )
        for field in class_info.fields:
            referenced_types = set(IDENTIFIER_PATTERN.findall(field.type_name)) & class_names
            for target in referenced_types - {class_info.name}:
                association_labels.setdefault((class_info.name, target), set()).add(field.name)

    for (source, target), field_names in sorted(association_labels.items()):
        graph.edge(
            source,
            target,
            dir="none",
            xlabel=", ".join(sorted(field_names)),
            color="#91a5a4",
            fontcolor="#506168",
            constraint="false",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_path = graph.render(
        filename=str(output_path.with_suffix("")),
        cleanup=True,
    )
    return Path(rendered_path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    source_dir = (args.source_dir or find_source_dir()).resolve()
    output_path = (args.output or Path(__file__).with_name("jemula_class_diagram.svg")).resolve()
    classes = parse_sources(source_dir)
    written_path = generate_graphviz_diagram(classes, source_dir, output_path)
    print(f"Parsed {len(classes)} Java types from {source_dir}")
    print(f"Wrote {written_path}")


if __name__ == "__main__":
    main()