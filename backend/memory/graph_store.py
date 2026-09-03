"""Session-scoped knowledge graph.

Two interchangeable backends behind one interface:

* `Neo4jGraphStore`   — Neo4j Aura Free, used when NEO4J_URI is configured.
* `NetworkXGraphStore` — in-process MultiDiGraph, used otherwise.

Every node and relationship carries `session_id`, and every query filters on it
(PRD section 6.1). Node labels stay plaintext: they drive the visualisation and
are low-sensitivity — the tradeoff is documented in the README.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache

import networkx as nx

from backend.config import Settings, get_settings
from backend.ingestion.extract import ALLOWED_NODE_TYPES, Entity, Relationship

log = logging.getLogger(__name__)

# Bounds on traversal, so one dense session cannot blow up a reply's context.
MAX_HOPS = 2
MAX_TRIPLES = 24


@dataclass(frozen=True)
class GraphNode:
    id: str  # lowercased name; unique within a session
    label: str  # display name
    type: str


@dataclass(frozen=True)
class GraphEdge:
    source: str
    target: str
    type: str


@dataclass
class GraphDelta:
    nodes: list[GraphNode]
    edges: list[GraphEdge]

    @property
    def counts(self) -> tuple[int, int]:
        return len(self.nodes), len(self.edges)

    def to_dict(self) -> dict[str, list[dict[str, str]]]:
        return {
            "nodes": [{"id": n.id, "label": n.label, "type": n.type} for n in self.nodes],
            "edges": [{"source": e.source, "target": e.target, "type": e.type} for e in self.edges],
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_label(node_type: str) -> str:
    """Labels are interpolated into Cypher, so only the fixed allowlist passes."""
    return node_type if node_type in ALLOWED_NODE_TYPES else "Concept"


def triple_to_sentence(source: str, rel_type: str, target: str) -> str:
    """Render an edge as a readable fact for the LLM context window."""
    verb = rel_type.replace("_", " ").lower()
    return f"{source} {verb} {target}"


class NetworkXGraphStore:
    """In-process fallback. One MultiDiGraph per session keeps isolation trivial."""

    remote = False

    def __init__(self) -> None:
        self._graphs: dict[str, nx.MultiDiGraph] = {}
        self._lock = asyncio.Lock()

    def _graph(self, session_id: str) -> nx.MultiDiGraph:
        return self._graphs.setdefault(session_id, nx.MultiDiGraph())

    async def ensure_ready(self) -> None:
        return None

    async def add(
        self, session_id: str, entities: list[Entity], relationships: list[Relationship]
    ) -> GraphDelta:
        async with self._lock:
            graph = self._graph(session_id)
            new_nodes: list[GraphNode] = []
            for entity in entities:
                if entity.key in graph:
                    continue
                graph.add_node(
                    entity.key,
                    label=entity.name,
                    type=_safe_label(entity.type),
                    session_id=session_id,
                    created_at=_now(),
                )
                new_nodes.append(GraphNode(entity.key, entity.name, _safe_label(entity.type)))

            new_edges: list[GraphEdge] = []
            for rel in relationships:
                if rel.source not in graph or rel.target not in graph:
                    continue
                if graph.has_edge(rel.source, rel.target, key=rel.type):
                    continue
                graph.add_edge(rel.source, rel.target, key=rel.type, session_id=session_id)
                new_edges.append(GraphEdge(rel.source, rel.target, rel.type))

            return GraphDelta(new_nodes, new_edges)

    async def get_graph(self, session_id: str) -> GraphDelta:
        graph = self._graph(session_id)
        nodes = [
            GraphNode(key, data.get("label", key), data.get("type", "Concept"))
            for key, data in graph.nodes(data=True)
        ]
        edges = [GraphEdge(u, v, k) for u, v, k in graph.edges(keys=True)]
        return GraphDelta(nodes, edges)

    async def neighbourhood(
        self, session_id: str, seeds: list[str], hops: int = MAX_HOPS
    ) -> list[str]:
        graph = self._graph(session_id)
        frontier = {s for s in seeds if s in graph}
        visited = set(frontier)
        triples: list[str] = []

        for _ in range(max(1, min(hops, MAX_HOPS))):
            next_frontier: set[str] = set()
            for node in frontier:
                for _, target, key in graph.out_edges(node, keys=True):
                    triples.append(triple_to_sentence(graph.nodes[node]["label"], key, graph.nodes[target]["label"]))
                    next_frontier.add(target)
                for source, _, key in graph.in_edges(node, keys=True):
                    triples.append(triple_to_sentence(graph.nodes[source]["label"], key, graph.nodes[node]["label"]))
                    next_frontier.add(source)
            frontier = next_frontier - visited
            visited |= next_frontier
            if not frontier:
                break

        return _dedupe(triples)[:MAX_TRIPLES]

    async def entity_keys(self, session_id: str) -> dict[str, str]:
        graph = self._graph(session_id)
        return {key: data.get("label", key) for key, data in graph.nodes(data=True)}

    async def delete_session(self, session_id: str) -> None:
        self._graphs.pop(session_id, None)

    async def close(self) -> None:
        return None


class Neo4jGraphStore:
    """Neo4j Aura Free. Nodes get both `:Entity` and their specific type label."""

    remote = True

    def __init__(self, settings: Settings) -> None:
        from neo4j import AsyncGraphDatabase

        self._driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
        self._ready = False
        self._lock = asyncio.Lock()

    async def ensure_ready(self) -> None:
        if self._ready:
            return
        async with self._lock:
            if self._ready:
                return
            async with self._driver.session() as session:
                await session.run(
                    "CREATE CONSTRAINT entity_key IF NOT EXISTS "
                    "FOR (n:Entity) REQUIRE (n.session_id, n.key) IS UNIQUE"
                )
            self._ready = True

    async def add(
        self, session_id: str, entities: list[Entity], relationships: list[Relationship]
    ) -> GraphDelta:
        await self.ensure_ready()
        new_nodes: list[GraphNode] = []
        new_edges: list[GraphEdge] = []

        async with self._driver.session() as session:
            for entity in entities:
                label = _safe_label(entity.type)
                result = await session.run(
                    f"""
                    MERGE (n:Entity {{session_id: $sid, key: $key}})
                    ON CREATE SET n.name = $name, n.type = $type,
                                  n.created_at = $now, n.created = true
                    ON MATCH SET n.created = false
                    SET n:`{label}`
                    RETURN n.created AS created
                    """,
                    sid=session_id,
                    key=entity.key,
                    name=entity.name,
                    type=label,
                    now=_now(),
                )
                record = await result.single()
                if record and record["created"]:
                    new_nodes.append(GraphNode(entity.key, entity.name, label))

            for rel in relationships:
                result = await session.run(
                    f"""
                    MATCH (a:Entity {{session_id: $sid, key: $src}})
                    MATCH (b:Entity {{session_id: $sid, key: $tgt}})
                    MERGE (a)-[r:`{rel.type}` {{session_id: $sid}}]->(b)
                    ON CREATE SET r.created_at = $now, r.created = true
                    ON MATCH SET r.created = false
                    RETURN r.created AS created
                    """,
                    sid=session_id,
                    src=rel.source,
                    tgt=rel.target,
                    now=_now(),
                )
                record = await result.single()
                if record and record["created"]:
                    new_edges.append(GraphEdge(rel.source, rel.target, rel.type))

        return GraphDelta(new_nodes, new_edges)

    async def get_graph(self, session_id: str) -> GraphDelta:
        await self.ensure_ready()
        async with self._driver.session() as session:
            node_rows = await (
                await session.run(
                    "MATCH (n:Entity {session_id: $sid}) RETURN n.key AS key, n.name AS name, n.type AS type",
                    sid=session_id,
                )
            ).data()
            edge_rows = await (
                await session.run(
                    """
                    MATCH (a:Entity {session_id: $sid})-[r]->(b:Entity {session_id: $sid})
                    WHERE r.session_id = $sid
                    RETURN a.key AS source, b.key AS target, type(r) AS type
                    """,
                    sid=session_id,
                )
            ).data()

        nodes = [GraphNode(r["key"], r["name"] or r["key"], r["type"] or "Concept") for r in node_rows]
        edges = [GraphEdge(r["source"], r["target"], r["type"]) for r in edge_rows]
        return GraphDelta(nodes, edges)

    async def neighbourhood(
        self, session_id: str, seeds: list[str], hops: int = MAX_HOPS
    ) -> list[str]:
        await self.ensure_ready()
        depth = max(1, min(int(hops), MAX_HOPS))  # not parameterisable in Cypher
        async with self._driver.session() as session:
            rows = await (
                await session.run(
                    f"""
                    MATCH (seed:Entity {{session_id: $sid}})
                    WHERE seed.key IN $seeds
                    MATCH path = (seed)-[rels*1..{depth}]-(:Entity {{session_id: $sid}})
                    WHERE all(rel IN rels WHERE rel.session_id = $sid)
                    UNWIND relationships(path) AS rel
                    WITH DISTINCT startNode(rel) AS a, rel, endNode(rel) AS b
                    RETURN a.name AS source, type(rel) AS type, b.name AS target
                    LIMIT $limit
                    """,
                    sid=session_id,
                    seeds=seeds,
                    limit=MAX_TRIPLES * 2,
                )
            ).data()

        return _dedupe(
            [triple_to_sentence(r["source"], r["type"], r["target"]) for r in rows]
        )[:MAX_TRIPLES]

    async def entity_keys(self, session_id: str) -> dict[str, str]:
        await self.ensure_ready()
        async with self._driver.session() as session:
            rows = await (
                await session.run(
                    "MATCH (n:Entity {session_id: $sid}) RETURN n.key AS key, n.name AS name",
                    sid=session_id,
                )
            ).data()
        return {r["key"]: r["name"] or r["key"] for r in rows}

    async def delete_session(self, session_id: str) -> None:
        async with self._driver.session() as session:
            await session.run("MATCH (n:Entity {session_id: $sid}) DETACH DELETE n", sid=session_id)

    async def close(self) -> None:
        await self._driver.close()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


@lru_cache(maxsize=1)
def get_graph_store() -> NetworkXGraphStore | Neo4jGraphStore:
    settings = get_settings()
    if settings.neo4j_enabled:
        return Neo4jGraphStore(settings)
    log.warning("NEO4J_URI unset — using in-process networkx graph (not durable)")
    return NetworkXGraphStore()
