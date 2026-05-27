"""Graph storage interface and in-memory implementation."""

from codegraph.graph.models import GraphNode, GraphEdge


class GraphStore:
    """Interface for graph data access."""

    def add_node(self, node: GraphNode) -> None:
        ...

    def add_edge(self, edge: GraphEdge) -> None:
        ...

    def get_node(self, node_id: str) -> GraphNode | None:
        ...

    def get_neighbors(self, node_id: str) -> list[tuple[GraphNode, GraphEdge]]:
        ...

    def search_nodes(self, query: str) -> list[GraphNode]:
        ...
