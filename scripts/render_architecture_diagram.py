"""Render the architecture diagram as editable SVG and portable PNG.

Documentation-only tool. Requires Pillow and Noto Sans or DejaVu Sans fonts.
Run from any directory: python3 scripts/render_architecture_diagram.py
No application imports, configuration, services or network access.
"""

from __future__ import annotations

import math
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/assets"
WIDTH, HEIGHT, SCALE = 1800, 1160, 2
INK, MUTED = "#172b44", "#52647a"
BLUE, PURPLE, TEAL = "#2563a6", "#7045b0", "#087e82"
SVG = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG)


def font_pair() -> tuple[Path, Path]:
    for directory, regular, bold in (
        ("/usr/share/fonts/noto", "NotoSans-Regular.ttf", "NotoSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/dejavu", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
    ):
        pair = Path(directory) / regular, Path(directory) / bold
        if all(path.is_file() for path in pair):
            return pair
    raise SystemExit("Install Noto Sans or DejaVu Sans to render documentation diagrams.")


class Diagram:
    def __init__(self):
        self.regular, self.bold = font_pair()
        self.image = Image.new("RGB", (WIDTH * SCALE, HEIGHT * SCALE), "#f7f9fc")
        self.draw = ImageDraw.Draw(self.image)
        self.svg = ET.Element(
            f"{{{SVG}}}svg",
            {"width": str(WIDTH), "height": str(HEIGHT), "viewBox": f"0 0 {WIDTH} {HEIGHT}",
             "role": "img", "aria-labelledby": "title description"},
        )
        self.node("title", {"id": "title"}).text = "Arquitectura hexagonal de El Espejo"
        self.node("desc", {"id": "description"}).text = (
            "Acceso invoca casos de uso dentro del hexágono. Core contiene reglas y puertos. "
            "Los adaptadores de salida implementan esos puertos. Bootstrap conecta los "
            "componentes. La franja inferior distingue las dependencias de código."
        )
        self.rect(0, 0, WIDTH, HEIGHT, "#f7f9fc", radius=0)

    def node(self, tag, attributes):
        return ET.SubElement(self.svg, f"{{{SVG}}}{tag}", attributes)

    def rect(self, x, y, width, height, fill, stroke=None, radius=18):
        self.node("rect", {"x": str(x), "y": str(y), "width": str(width),
                           "height": str(height), "rx": str(radius), "fill": fill,
                           "stroke": stroke or "none", "stroke-width": "2"})
        self.draw.rounded_rectangle(
            (x * SCALE, y * SCALE, (x + width) * SCALE, (y + height) * SCALE),
            radius=radius * SCALE, fill=fill, outline=stroke, width=2 * SCALE,
        )

    def polygon(self, points, fill, stroke):
        self.node("polygon", {"points": " ".join(f"{x},{y}" for x, y in points),
                              "fill": fill, "stroke": stroke, "stroke-width": "3"})
        scaled = [(x * SCALE, y * SCALE) for x, y in points]
        self.draw.polygon(scaled, fill=fill)
        self.draw.line([*scaled, scaled[0]], fill=stroke, width=3 * SCALE, joint="curve")

    def text(self, x, baseline, value, size=22, color=INK, bold=False, center=False):
        font = ImageFont.truetype(str(self.bold if bold else self.regular), size * SCALE)
        bounds = self.draw.textbbox((x * SCALE, baseline * SCALE), value, font=font,
                                    anchor="ms" if center else "ls")
        if bounds[0] < 0 or bounds[1] < 0 or bounds[2] > WIDTH * SCALE \
                or bounds[3] > HEIGHT * SCALE:
            raise ValueError(f"Diagram text would be clipped: {value}")
        self.draw.text((x * SCALE, baseline * SCALE), value, font=font, fill=color,
                       anchor="ms" if center else "ls")
        self.node("text", {"x": str(x), "y": str(baseline), "fill": color,
                           "font-size": str(size), "font-weight": "700" if bold else "400",
                           "font-family": "Noto Sans, DejaVu Sans, sans-serif",
                           "text-anchor": "middle" if center else "start"}).text = value

    def line(self, points, color, dashed=False, arrow=False):
        self.node("polyline", {"points": " ".join(f"{x},{y}" for x, y in points),
                               "fill": "none", "stroke": color, "stroke-width": "3",
                               "stroke-linejoin": "round",
                               "stroke-dasharray": "9 7" if dashed else "none"})
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            distance = math.hypot(x2 - x1, y2 - y1)
            if dashed:
                for start in range(0, int(distance), 16):
                    stop = min(start + 9, distance)
                    a = (x1 + (x2 - x1) * start / distance,
                         y1 + (y2 - y1) * start / distance)
                    b = (x1 + (x2 - x1) * stop / distance,
                         y1 + (y2 - y1) * stop / distance)
                    self.draw.line([(a[0] * SCALE, a[1] * SCALE),
                                    (b[0] * SCALE, b[1] * SCALE)], fill=color, width=3 * SCALE)
            else:
                self.draw.line([(x1 * SCALE, y1 * SCALE), (x2 * SCALE, y2 * SCALE)],
                               fill=color, width=3 * SCALE)
        if arrow:
            (x1, y1), (x2, y2) = points[-2:]
            angle = math.atan2(y2 - y1, x2 - x1)
            points = [(x2, y2)] + [
                (x2 - 15 * math.cos(angle + offset), y2 - 15 * math.sin(angle + offset))
                for offset in (-0.45, 0.45)
            ]
            self.polygon(points, color, color)

    def save(self):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        self.image.save(OUTPUT / "hexagonal-architecture.png", optimize=True)
        ET.indent(self.svg)
        ET.ElementTree(self.svg).write(OUTPUT / "hexagonal-architecture.svg",
                                      encoding="utf-8", xml_declaration=True)


def main():
    d = Diagram()
    d.text(64, 66, "EL ESPEJO  /  BACKEND", 18, MUTED, bold=True)
    d.text(64, 121, "Arquitectura hexagonal", 42, bold=True)
    d.text(1390, 116, "ORGANIZACIÓN OBJETIVO", 18, MUTED)

    d.polygon([(550, 180), (1320, 180), (1440, 500), (1320, 820),
               (550, 820), (410, 500)], "#eef2fc", "#bbc8e2")
    d.text(900, 228, "INTERIOR DEL HEXÁGONO", 21, BLUE, bold=True, center=True)
    d.text(900, 264, "Aplicación independiente de sus tecnologías", 20, MUTED, center=True)

    d.rect(64, 300, 310, 390, "#eaf3ff", "#bdd3ef")
    d.text(92, 344, "Adaptadores", 28, BLUE, bold=True)
    d.text(92, 380, "de acceso", 28, BLUE, bold=True)
    d.text(92, 428, "adapters/access/", 19, MUTED)
    for y, title, detail in ((482, "API", "Pública y administrativa"),
                             (558, "CLI", "Comandos operativos"),
                             (634, "Workers", "Recepción de entregas Taskiq")):
        d.text(92, y, title, 22, bold=True)
        d.text(92, y + 29, detail, 17, MUTED)

    d.text(900, 307, "Puerto de entrada: acción pública del caso de uso", 19, BLUE, center=True)
    d.rect(650, 332, 500, 130, "#ffffff", "#b8ccec")
    d.text(900, 377, "use_cases/", 30, BLUE, bold=True, center=True)
    d.text(900, 413, "Autoriza y coordina acciones", 22, center=True)
    d.text(900, 442, "Recibe contratos, no clientes concretos", 18, MUTED, center=True)

    d.rect(600, 535, 740, 190, "#ffffff", "#c9b9e5")
    d.text(630, 578, "core/", 30, PURPLE, bold=True)
    d.text(630, 623, "Modelos · reglas · políticas", 23)
    d.text(630, 661, "Entidades, evidencia y transiciones", 20, MUTED)
    d.text(630, 693, "Sin HTTP, ORM, SDKs ni I/O concreto", 18, MUTED)
    d.rect(1160, 574, 150, 112, "#f2ebfc", "#c9b9e5", radius=12)
    d.text(1235, 611, "Puertos", 23, PURPLE, bold=True, center=True)
    d.text(1235, 641, "de salida", 21, PURPLE, center=True)
    d.text(1235, 668, "Contratos", 17, MUTED, center=True)

    d.line([(374, 490), (520, 490), (520, 397), (650, 397)], BLUE, arrow=True)
    d.text(522, 373, "invoca", 18, BLUE)
    d.line([(900, 462), (900, 535)], PURPLE, arrow=True)
    d.text(922, 507, "aplica reglas", 17, PURPLE)
    d.line([(1150, 397), (1235, 397), (1235, 574)], PURPLE, arrow=True)
    d.text(1252, 464, "usa", 18, PURPLE)
    d.line([(1310, 630), (1420, 630), (1420, 490), (1450, 490)], TEAL, arrow=True)

    d.rect(1450, 300, 310, 426, "#e9f6f3", "#acd8ce")
    d.text(1478, 344, "Adaptadores", 28, TEAL, bold=True)
    d.text(1478, 380, "de salida", 28, TEAL, bold=True)
    for y, title, details in (
        (434, "Storage", ["PostgreSQL · ArcadeDB", "Filesystem"]),
        (548, "Providers", ["OpenAI · email · Web Push"]),
        (636, "Messaging", ["RabbitMQ"]),
    ):
        d.text(1478, y, title, 22, bold=True)
        for index, detail in enumerate(details):
            d.text(1478, y + 31 + index * 27, detail, 18, MUTED)
    d.text(1605, 754, "Implementan los puertos de core", 17, TEAL, center=True)

    d.rect(500, 865, 820, 106, "#f0edf7", "#d3c6e5")
    d.text(910, 906, "bootstrap/", 29, PURPLE, bold=True, center=True)
    d.text(910, 943, "Construye, inyecta y gestiona recursos de cada proceso", 20, center=True)
    d.line([(500, 918), (218, 918), (218, 690)], PURPLE, dashed=True)
    d.line([(1320, 918), (1605, 918), (1605, 775)], PURPLE, dashed=True)
    d.line([(910, 865), (910, 820)], PURPLE, dashed=True)

    d.rect(64, 1010, 1696, 106, "#172b44", radius=16)
    d.text(92, 1047, "DEPENDENCIAS DE CÓDIGO  /  DIRECCIÓN DE LOS IMPORTS", 18,
           "#b8d0e8", bold=True)
    for x, value in ((92, "acceso"), (275, "use_cases"), (505, "core"),
                     (740, "salida"), (930, "core"), (1160, "bootstrap"),
                     (1410, "componentes")):
        d.text(x, 1089, value, 24, "#ffffff", bold=True)
    for start, stop in ((195, 250), (433, 482), (845, 905), (1330, 1385)):
        d.line([(start, 1082), (stop, 1082)], "#b8d0e8", arrow=True)
    d.text(64, 1145, "Flechas sólidas: llamadas en ejecución. Líneas discontinuas: composición. "
           "La aplicación no importa adaptadores.", 17, MUTED)
    d.save()
    print("Rendered docs/assets/hexagonal-architecture.svg and .png")


if __name__ == "__main__":
    main()
