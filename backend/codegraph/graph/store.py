"""Graph storage interface and in-memory implementation."""

from __future__ import annotations

from codegraph.graph.models import GraphNode, GraphEdge, CodeGraph


class GraphStore:
    """In-memory graph store with edge indexing.

    Maintains node and edge lookup tables for fast neighbor/query access.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        # Indexes: source_id -> edges, target_id -> edges
        self._edges_by_source: dict[str, list[GraphEdge]] = {}
        self._edges_by_target: dict[str, list[GraphEdge]] = {}

    # ── Node operations ────────────────────────────────────────────────

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node

    def add_nodes(self, nodes: list[GraphNode]) -> None:
        for node in nodes:
            self._nodes[node.id] = node

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def all_nodes(self) -> list[GraphNode]:
        return list(self._nodes.values())

    def node_count(self) -> int:
        return len(self._nodes)

    # ── Edge operations ────────────────────────────────────────────────

    def add_edge(self, edge: GraphEdge) -> None:
        self._edges.append(edge)
        self._edges_by_source.setdefault(edge.source, []).append(edge)
        self._edges_by_target.setdefault(edge.target, []).append(edge)

    def add_edges(self, edges: list[GraphEdge]) -> None:
        for edge in edges:
            self.add_edge(edge)

    def all_edges(self) -> list[GraphEdge]:
        return list(self._edges)

    def edge_count(self) -> int:
        return len(self._edges)

    # ── Neighbor / traversal ───────────────────────────────────────────

    def get_neighbors(self, node_id: str) -> list[tuple[GraphNode, GraphEdge]]:
        """Return (neighbor_node, connecting_edge) for both directions."""
        result: dict[str, tuple[GraphNode, GraphEdge]] = {}
        seen: set[str] = set()

        for edge in self._edges_by_source.get(node_id, []):
            target_node = self._nodes.get(edge.target)
            if target_node and edge.target not in seen:
                seen.add(edge.target)
                result[edge.target] = (target_node, edge)

        for edge in self._edges_by_target.get(node_id, []):
            source_node = self._nodes.get(edge.source)
            if source_node and edge.source not in seen:
                seen.add(edge.source)
                result[edge.source] = (source_node, edge)

        return list(result.values())

    def get_outgoing_edges(self, node_id: str) -> list[GraphEdge]:
        return list(self._edges_by_source.get(node_id, []))

    def get_incoming_edges(self, node_id: str) -> list[GraphEdge]:
        return list(self._edges_by_target.get(node_id, []))

    # ── Search ─────────────────────────────────────────────────────────

    def search_nodes(self, query: str) -> list[GraphNode]:
        """Search nodes by id, name, file_path, qualified_name.

        Empty query returns all nodes.
        """
        if not query:
            return self.all_nodes()

        q = query.lower()
        results: list[GraphNode] = []
        seen: set[str] = set()

        for node in self._nodes.values():
            if node.id in seen:
                continue
            if q in node.id.lower():
                results.append(node)
                seen.add(node.id)
                continue
            if q in node.name.lower():
                results.append(node)
                seen.add(node.id)
                continue
            if q in node.file_path.lower():
                results.append(node)
                seen.add(node.id)
                continue
            if node.qualified_name and q in node.qualified_name.lower():
                results.append(node)
                seen.add(node.id)
                continue
            if node.docstring and q in node.docstring.lower():
                results.append(node)
                seen.add(node.id)
                continue

        return results

    # ── Bulk load ──────────────────────────────────────────────────────

    def load_from_graph(self, graph: CodeGraph) -> None:
        """Populate the store from a CodeGraph container."""
        self.add_nodes(graph.nodes)
        self.add_edges(graph.edges)

    def load_from_lists(
        self, nodes: list[GraphNode], edges: list[GraphEdge]
    ) -> None:
        """Populate the store from raw node/edge lists."""
        self.add_nodes(nodes)
        self.add_edges(edges)

    def remove_node(self, node_id: str) -> bool:
        """Remove a single node by ID. Returns True if removed."""
        if node_id not in self._nodes:
            return False
        del self._nodes[node_id]
        return True

    def remove_edges_by_file(self, file_path: str) -> int:
        """Remove all edges where either endpoint belongs to *file_path*.

        First collects node IDs that belong to the file, then removes
        all edges touching those nodes. Returns the count removed.
        """
        file_node_ids = {
            nid for nid, n in self._nodes.items()
            if n.file_path == file_path
        }
        if not file_node_ids:
            return 0

        removed = 0
        kept: list[GraphEdge] = []
        for e in self._edges:
            if e.source in file_node_ids or e.target in file_node_ids:
                removed += 1
            else:
                kept.append(e)

        self._edges = kept
        self._edges_by_source.clear()
        self._edges_by_target.clear()
        for e in kept:
            self._edges_by_source.setdefault(e.source, []).append(e)
            self._edges_by_target.setdefault(e.target, []).append(e)

        return removed

    def remove_nodes_by_file(self, file_path: str) -> int:
        """Remove all nodes belonging to *file_path*. Returns count removed.

        Also removes all edges touching those nodes.
        """
        to_remove = [
            nid for nid, n in self._nodes.items()
            if n.file_path == file_path
        ]
        self.remove_edges_by_file(file_path)
        for nid in to_remove:
            del self._nodes[nid]
        return len(to_remove)

    def clear(self) -> None:
        """Remove all data from the store."""
        self._nodes.clear()
        self._edges.clear()
        self._edges_by_source.clear()
        self._edges_by_target.clear()
