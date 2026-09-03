"""The extractor is fed model output, so parsing must never trust its shape."""

from backend.ingestion.extract import parse


def test_parses_well_formed_json() -> None:
    entities, relationships = parse(
        '{"nodes":[{"name":"User","type":"Person"},{"name":"Acme","type":"Organization"}],'
        '"relationships":[{"source":"User","type":"WORKS_AT","target":"Acme"}]}'
    )
    assert {(e.name, e.type) for e in entities} == {("User", "Person"), ("Acme", "Organization")}
    assert [(r.source, r.type, r.target) for r in relationships] == [("user", "WORKS_AT", "acme")]


def test_strips_markdown_fences() -> None:
    entities, _ = parse('```json\n{"nodes":[{"name":"Lisbon","type":"Place"}]}\n```')
    assert [e.name for e in entities] == ["Lisbon"]


def test_recovers_json_from_chatty_output() -> None:
    entities, _ = parse('Sure! Here you go: {"nodes":[{"name":"Lisbon","type":"Place"}]} Hope that helps.')
    assert [e.name for e in entities] == ["Lisbon"]


def test_unknown_node_types_become_concept() -> None:
    entities, _ = parse('{"nodes":[{"name":"Jazz","type":"MusicalGenre"}]}')
    assert entities[0].type == "Concept"


def test_relationship_types_are_sanitised() -> None:
    """Types are interpolated into Cypher, so injection must not survive parsing."""
    _, relationships = parse(
        '{"nodes":[{"name":"User","type":"Person"},{"name":"Acme","type":"Organization"}],'
        '"relationships":[{"source":"User","type":"works at` {}]->() DETACH DELETE n //","target":"Acme"}]}'
    )
    assert relationships[0].type == "WORKS_AT_DETACH_DELETE_N"


def test_drops_dangling_and_self_edges() -> None:
    _, relationships = parse(
        '{"nodes":[{"name":"User","type":"Person"}],'
        '"relationships":['
        '{"source":"User","type":"KNOWS","target":"Ghost"},'
        '{"source":"User","type":"KNOWS","target":"User"}]}'
    )
    assert relationships == []


def test_deduplicates_repeated_triples() -> None:
    _, relationships = parse(
        '{"nodes":[{"name":"User","type":"Person"},{"name":"Acme","type":"Organization"}],'
        '"relationships":['
        '{"source":"User","type":"WORKS_AT","target":"Acme"},'
        '{"source":"user","type":"WORKS_AT","target":"acme"}]}'
    )
    assert len(relationships) == 1


def test_garbage_returns_empty_rather_than_raising() -> None:
    for raw in ["", "not json at all", "[1,2,3]", '{"nodes":"nope"}']:
        assert parse(raw) == ([], [])
