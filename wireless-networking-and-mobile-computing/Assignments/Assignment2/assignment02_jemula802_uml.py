"""Generate a UML diagram from Jemula802 engine Java sources.

Install dependencies with ``python -m pip install graphviz tree-sitter-language-pack``.
Graphviz's ``dot`` executable must also be installed and available on PATH.
Run this file to write ``jemula802_engine_class_diagram.svg`` next to the script.
"""

from __future__ import annotations

import argparse
import html
import math
import re
from dataclasses import dataclass
from pathlib import Path

from graphviz import Digraph
from tree_sitter_language_pack import get_parser


SELECTED_CLASS_NAMES = (
    "JE802Control",
    "JE802Station",
    "JEWirelessMedium",
    "JE802Phy",
    "JE802_11Phy",
    "JE802_11Mac",
    "JE802_11MacAlgorithm",
    "JE802StatEval",
)
CLASS_TYPES = {
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
}
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_$][\w$]*")
RELEVANT_FIELD_WORDS = (
    "station",
    "mac",
    "phy",
    "medium",
    "eval",
    "algorithm",
    "thrp",
    "offer",
    "delay",
    "result",
    "path",
)


@dataclass
class FieldInfo:
    name: str
    type_name: str
    visibility: str
    is_static: bool

    def label(self) -> str:
        visibility = {"public": "+", "protected": "#", "private": "-"}.get(
            self.visibility, "~"
        )
        static = " {static}" if self.is_static else ""
        return f"{visibility} {self.name}: {self.type_name}{static}"


@dataclass
class JavaType:
    name: str
    package: str
    kind: str
    parent: str | None
    fields: list[FieldInfo]


def node_text(node) -> str:
    if node is None:
        return ""
    text = node.text
    return text.decode("utf-8") if text is not None else ""


def find_source_dir() -> Path:
    relative_path = Path("notebooks/01 Jemula/jemula-project/simulator/engine/src")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / relative_path
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "Could not find notebooks/01 Jemula/jemula-project/simulator/engine/src "
        "relative to this script. Pass --source-dir to specify it."
    )


def parse_field(field_node) -> list[FieldInfo]:
    type_node = field_node.child_by_field_name("type")
    if type_node is None:
        return []

    type_name = node_text(type_node).strip()
    modifiers_node = field_node.child_by_field_name("modifiers")
    modifiers = node_text(modifiers_node) if modifiers_node else ""
    visibility = next(
        (item for item in ("public", "protected", "private") if item in modifiers),
        "package",
    )
    is_static = "static" in modifiers.split()

    fields = []
    for variable in field_node.named_children:
        if variable.type != "variable_declarator":
            continue
        name_node = variable.child_by_field_name("name")
        if name_node is not None:
            fields.append(
                FieldInfo(node_text(name_node), type_name, visibility, is_static)
            )
    return fields


def parse_engine_sources(source_dir: Path) -> tuple[list[JavaType], int]:
    parser = get_parser("java")
    java_types = []
    source_count = 0

    for source_path in sorted(source_dir.rglob("*.java")):
        source_count += 1
        tree = parser.parse(source_path.read_bytes())
        if tree.root_node.has_error:
            raise SyntaxError(f"Could not parse Java source: {source_path}")

        package_node = next(
            (
                child
                for child in tree.root_node.named_children
                if child.type == "package_declaration"
            ),
            None,
        )
        package = node_text(package_node).removeprefix("package ").removesuffix(";").strip()

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
            superclass_node = declaration.child_by_field_name("superclass")
            parent_identifiers = IDENTIFIER_PATTERN.findall(node_text(superclass_node))
            parent = parent_identifiers[-1] if parent_identifiers else None
            java_types.append(
                JavaType(
                    name=node_text(name_node),
                    package=package,
                    kind=declaration.type.removesuffix("_declaration"),
                    parent=parent,
                    fields=fields,
                )
            )

    if not java_types:
        raise ValueError(f"No Java types found under {source_dir}")
    return java_types, source_count


def field_priority(field: FieldInfo, selected_names: set[str]) -> tuple[int, str]:
    references_selected = bool(set(IDENTIFIER_PATTERN.findall(field.type_name)) & selected_names)
    has_relevant_name = any(word in field.name.lower() for word in RELEVANT_FIELD_WORDS)
    return (-(2 * references_selected + has_relevant_name), field.name)


def class_label(java_type: JavaType, selected_names: set[str]) -> str:
    fields = sorted(java_type.fields, key=lambda field: field_priority(field, selected_names))
    rows = [
        '<TR><TD ALIGN="LEFT" BGCOLOR="#e5f0ed">'
        f'<FONT FACE="Segoe UI" POINT-SIZE="9" COLOR="#26756f">'
        f"{html.escape(java_type.package)} :: {html.escape(java_type.kind)}</FONT></TD></TR>",
        '<TR><TD ALIGN="LEFT"><FONT FACE="Segoe UI" POINT-SIZE="14"><B>'
        f"{html.escape(java_type.name)}</B></FONT></TD></TR>",
    ]
    if java_type.parent:
        rows.append(
            '<TR><TD ALIGN="LEFT"><FONT FACE="Segoe UI" POINT-SIZE="9" COLOR="#66777a">'
            f"extends {html.escape(java_type.parent)}</FONT></TD></TR>"
        )
    rows.append('<HR COLOR="#dbe3e1"/>')

    for field in fields[:6]:
        label = field.label()
        if len(label) > 42:
            label = f"{label[:39]}..."
        rows.append(
            '<TR><TD ALIGN="LEFT"><FONT FACE="Consolas" POINT-SIZE="9">'
            f"{html.escape(label)}</FONT></TD></TR>"
        )
    if len(fields) > 6:
        rows.append(
            '<TR><TD ALIGN="LEFT"><FONT FACE="Segoe UI" POINT-SIZE="9" COLOR="#506168">'
            f"... +{len(fields) - 6} fields</FONT></TD></TR>"
        )
    if not fields:
        rows.append(
            '<TR><TD ALIGN="LEFT"><FONT FACE="Segoe UI" POINT-SIZE="9">(no fields)</FONT></TD></TR>'
        )

    return (
        '<<TABLE BORDER="1" COLOR="#c6d2d0" CELLBORDER="0" CELLSPACING="0" '
        'CELLPADDING="6" BGCOLOR="#ffffff">'
        f"{''.join(rows)}</TABLE>>"
    )


def render_diagram(java_types: list[JavaType], source_dir: Path, output_path: Path) -> Path:
    by_name = {java_type.name: java_type for java_type in java_types}
    missing = set(SELECTED_CLASS_NAMES) - set(by_name)
    if missing:
        raise ValueError(f"Selected engine classes not found: {', '.join(sorted(missing))}")
    selected = [by_name[name] for name in SELECTED_CLASS_NAMES]
    selected_names: set[str] = set(SELECTED_CLASS_NAMES)

    graph = Digraph("Jemula802Engine", format="svg", engine="dot")
    graph.attr(
        "graph",
        rankdir="TB",
        bgcolor="#f3f5f2",
        pad="0.35",
        nodesep="0.45",
        ranksep="0.7",
        splines="ortho",
        labelloc="t",
        label=(
            "Jemula802 Engine Class Diagram\\n"
            f"8 selected classes from {len(java_types)} Java types in {source_dir}"
        ),
        fontname="Segoe UI",
        fontsize="20",
        fontcolor="#1c2b32",
    )
    graph.attr("node", shape="plain", margin="0")
    graph.attr("edge", fontname="Segoe UI", fontsize="9", color="#829694")

    for java_type in selected:
        graph.node(java_type.name, label=class_label(java_type, selected_names))

    associations: dict[tuple[str, str], set[str]] = {}
    for java_type in selected:
        if java_type.parent in selected_names:
            graph.edge(
                java_type.name,
                java_type.parent,
                arrowhead="empty",
                color="#52666d",
                penwidth="1.5",
            )
        for field in java_type.fields:
            targets = set(IDENTIFIER_PATTERN.findall(field.type_name)) & selected_names
            for target in targets - {java_type.name}:
                associations.setdefault((java_type.name, target), set()).add(field.name)

    for (source, target), fields in sorted(associations.items()):
        graph.edge(
            source,
            target,
            dir="none",
            xlabel=", ".join(sorted(fields)),
            color="#91a5a4",
            fontcolor="#506168",
            constraint="false",
        )

    graph.node(
        "KernelFoundation",
        shape="note",
        style="filled",
        fillcolor="#e8eceb",
        color="#aebbb9",
        fontname="Segoe UI",
        fontsize="10",
        label=(
            "Kernel foundation\\n"
            "JE802Control owns JEEventScheduler\\n"
            "Event handlers inherit JEEventHandler\\n"
            "JE802_11Mlme owns the MAC algorithm"
        ),
    )
    graph.edge(
        "JE802Control",
        "KernelFoundation",
        style="dashed",
        arrowhead="none",
        color="#9aa9a7",
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
    output_path = (
        args.output or Path(__file__).with_name("jemula802_engine_class_diagram.svg")
    ).resolve()
    java_types, source_count = parse_engine_sources(source_dir)
    written_path = render_diagram(java_types, source_dir, output_path)
    print(f"Scanned {source_count} Java files and {len(java_types)} top-level types")
    print(f"Highlighted {len(SELECTED_CLASS_NAMES)} core engine classes")
    print(f"Wrote {written_path}")


if __name__ == "__main__":
    main()
