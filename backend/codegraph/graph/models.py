"""Graph data models — Node, Edge, and confidence types."""

from enum import Enum
from pydantic import BaseModel, Field


class NodeType(str, Enum):
    module = "module"
    class_ = "class"
    function = "function"
    method = "method"


class EdgeType(str, Enum):
    call = "call"
    import_ = "import"
    inheritance = "inheritance"
    contains = "contains"


class Confidence(str, Enum):
    exact = "exact"
    heuristic = "heuristic"
    weak = "weak"


class Position(BaseModel):
    start_line: int
    end_line: int


class GraphNode(BaseModel):
    id: str
    name: str
    type: NodeType
    file_path: str
    position: Position | None = None
    docstring: str | None = None


class GraphEdge(BaseModel):
    source_id: str
    target_id: str
    type: EdgeType
    confidence: Confidence
    resolution: str | None = None
