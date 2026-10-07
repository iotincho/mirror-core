"""Layer presentation declarations, independent of provider construction.

Register new layers here, including nonvisual layers. Availability always comes
from the document graph, never from this catalog alone.
"""

from src.graph.contracts import GraphLayer

LAYER_PRESENTATIONS = {
    "emotions": GraphLayer(id="emotions", label="Emociones"),
}


def layer_presentation(name: str) -> GraphLayer:
    return LAYER_PRESENTATIONS.get(name) or GraphLayer(
        id=name, label=name.replace("_", " ").capitalize()
    )
