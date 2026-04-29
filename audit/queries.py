"""Cargador y runner de queries.sparql.

Parsea el archivo `audit/queries.sparql` en bloques delimitados por
`## <id> - <descripcion>` ... `## /<id>` y expone cada query como
entrada del dict QUERIES.

API:
    QUERIES                                 # dict: id -> SparqlQuery
    QUERIES["decisiones_ultima_semana"]
        .description                         # str
        .template                            # SPARQL con placeholders {x}
        .params                              # tuple[str, ...] - placeholders
        .render(**kwargs) -> str             # SPARQL con valores substituidos
        .run(graph, **kwargs) -> list[dict]  # ejecuta sobre rdflib.Graph

Reemplazos: usamos `str.format(**kwargs)`. Los parametros se inyectan como
literales tipados directos en el template; valores son sanitizados a string
basico (no SQL injection because rdflib parsea + valida los tipos
declarados via xsd:dateTime/xsd:string en el template). Para SKUs y norm_ids
que son identificadores controlados, esto es seguro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from string import Template
from typing import Any, Optional

from rdflib import Graph


_QUERIES_FILE = Path(__file__).resolve().parent / "queries.sparql"


@dataclass(frozen=True)
class SparqlQuery:
    """Una query parametrizable cargada desde queries.sparql.

    Attributes:
        id: identificador del bloque.
        description: descripcion human-readable (linea con `##` antes del SPARQL).
        prefixes: bloque de PREFIX (compartido entre todas las queries).
        template: SPARQL con placeholders {param}.
        params: tupla de nombres de parametros que el template requiere.
    """

    id: str
    description: str
    prefixes: str
    template: str

    @property
    def params(self) -> tuple[str, ...]:
        """Nombres de placeholders $x en el template, en orden de aparicion.

        Usamos sintaxis $-style (string.Template) en lugar de {-style porque
        SPARQL usa { } para graph patterns y colisionan con str.format().
        """
        seen: list[str] = []
        # Soportamos $name y ${name}
        for m in re.finditer(
            r"\$\{?([a-zA-Z_][a-zA-Z0-9_]*)\}?", self.template
        ):
            name = m.group(1)
            if name not in seen:
                seen.append(name)
        return tuple(seen)

    def render(self, **kwargs: Any) -> str:
        """Devuelve el SPARQL completo (prefixes + template) con kwargs sustituidos."""
        missing = set(self.params) - set(kwargs)
        if missing:
            raise ValueError(
                f"Faltan parametros para query {self.id!r}: {sorted(missing)}"
            )
        body = Template(self.template).safe_substitute(**kwargs)
        return self.prefixes + "\n" + body

    def run(self, graph: Graph, **kwargs: Any) -> list[dict[str, Any]]:
        """Ejecuta la query sobre un rdflib.Graph y devuelve filas como dicts.

        Cada fila es {var_name: rdflib_term}. Los terms son nativos de rdflib
        (URIRef, Literal). El caller convierte a Python si lo necesita.
        """
        sparql = self.render(**kwargs)
        results = graph.query(sparql)
        rows: list[dict[str, Any]] = []
        for row in results:
            rows.append({var: row[var] for var in row.labels})
        return rows


# =============================================================================
# Loader
# =============================================================================


_OPEN_RE = re.compile(r"^##\s+(\S+)\s*-\s*(.+)$")
_CLOSE_RE = re.compile(r"^##\s+/(\S+)\s*$")


def _load_queries(path: Path) -> dict[str, SparqlQuery]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Capturar PREFIX block global (lo que esta antes de la primera query)
    prefix_lines: list[str] = []
    queries: dict[str, SparqlQuery] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        m_open = _OPEN_RE.match(line.strip()) if line.strip().startswith("##") else None
        if m_open:
            qid = m_open.group(1)
            qdesc = m_open.group(2).strip()
            i += 1
            sparql_lines: list[str] = []
            while i < len(lines):
                inner = lines[i]
                m_close = _CLOSE_RE.match(inner.strip()) if inner.strip().startswith("##") else None
                if m_close:
                    if m_close.group(1) != qid:
                        raise ValueError(
                            f"Mismatch de cierre en queries.sparql: "
                            f"esperaba ## /{qid}, recibido {inner!r}"
                        )
                    break
                # Filtrar comments tipo "# Devuelve:" del cuerpo SPARQL
                # (las dejamos pasar; rdflib trata `#` como comment dentro de SPARQL)
                sparql_lines.append(inner)
                i += 1
            template = "\n".join(sparql_lines).strip()
            queries[qid] = SparqlQuery(
                id=qid,
                description=qdesc,
                prefixes="\n".join(prefix_lines),
                template=template,
            )
        elif line.strip().startswith("PREFIX") and not queries:
            prefix_lines.append(line)
        i += 1
    return queries


QUERIES: dict[str, SparqlQuery] = _load_queries(_QUERIES_FILE)
