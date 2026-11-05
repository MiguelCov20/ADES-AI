"""Esquema del grafo de código en Neo4j (ADES-AI, Fase 2).

Define los nodos, relaciones, constraints e índices que construye
memory/indexer.py a partir del código (Tree-sitter). Es el "RepoMap"
anti-alucinación: el agente consulta la estructura sin cargar todo el código.
"""
from neo4j import Driver

# Nodos: CodeFile, Class, Function, Module
# Relaciones:
#   (CodeFile)-[:CONTAINS]->(Class|Function)
#   (Class)-[:CONTAINS]->(Function)      # métodos
#   (Class)-[:INHERITS]->(Class)         # superclases
#   (CodeFile)-[:IMPORTS]->(Module)
#   (Function)-[:CALLS]->(Function)      # llamadas intra-archivo (mejor esfuerzo)

CONSTRAINTS = [
    "CREATE CONSTRAINT codefile_path IF NOT EXISTS FOR (n:CodeFile) REQUIRE n.path IS UNIQUE",
    "CREATE CONSTRAINT class_fqn IF NOT EXISTS FOR (n:Class) REQUIRE n.full_name IS UNIQUE",
    "CREATE CONSTRAINT function_fqn IF NOT EXISTS FOR (n:Function) REQUIRE n.full_name IS UNIQUE",
    "CREATE CONSTRAINT module_name IF NOT EXISTS FOR (n:Module) REQUIRE n.name IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX codefile_lang IF NOT EXISTS FOR (n:CodeFile) ON (n.language)",
    "CREATE INDEX class_name IF NOT EXISTS FOR (n:Class) ON (n.name)",
    "CREATE INDEX function_name IF NOT EXISTS FOR (n:Function) ON (n.name)",
]


def init_schema(driver: Driver) -> None:
    """Crea constraints e índices (idempotente)."""
    with driver.session() as session:
        for stmt in CONSTRAINTS + INDEXES:
            session.run(stmt)


def clear_graph(driver: Driver) -> None:
    """Elimina todos los nodos del grafo de código (útil para reindexar desde cero)."""
    with driver.session() as session:
        session.run(
            "MATCH (n) WHERE n:CodeFile OR n:Class OR n:Function OR n:Module "
            "DETACH DELETE n"
        )
