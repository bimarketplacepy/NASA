"""
rag/client.py
--------------
RAGClient: cliente Python de busqueda semantica sobre los catalogos de
proveedores indexados en ChromaDB.

Tarea 1 - Bloque 8.

Este es el SEGUNDO PRODUCTO FINAL de la Tarea 1 (la primera mitad fue
OntologyClient). Permite al resto del equipo (Tarea 4 optimizador, Tarea 5
agentes) hacer preguntas en lenguaje natural sobre los catalogos sin
preocuparse por embeddings, vector stores ni Cypher.

Uso basico:

    from rag import RAGClient

    with RAGClient() as rag:
        # Busqueda libre en todos los catalogos
        resultados = rag.buscar("MOQ tipico desde China", k=5)
        for r in resultados:
            print(r["score"], r["proveedor_nombre"], r["texto"][:200])

        # Busqueda filtrada a un proveedor especifico
        resultados = rag.buscar(
            "condiciones de pago",
            k=3,
            proveedor_id="SUP-01"   # solo en DALIAN_MIRO
        )

Los proveedor_id usados en los catalogos sinteticos siguen el formato
"SUP-01", "SUP-02", etc. Cuando se reemplacen por catalogos reales mapeados
a Pegasus, este mismo metodo va a aceptar COD_PROVEEDOR de Pegasus.
"""

from pathlib import Path
from typing import Optional

import chromadb
from chromadb.utils import embedding_functions


CHROMA_DIR = Path(__file__).parent.parent / "chroma_db"
COLLECTION_NAME = "catalogos_proveedores"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


class RAGClient:
    """
    Cliente de busqueda semantica sobre los catalogos PDF de proveedores
    indexados en ChromaDB.

    Internamente usa el mismo modelo de embeddings que se uso para indexar
    (paraphrase-multilingual-MiniLM-L12-v2, soporta español). Las consultas
    devuelven resultados ordenados por similitud coseno.

    Es seguro reutilizar la misma instancia durante una sesion. Llamar a
    close() al terminar (o usar como context manager).
    """

    def __init__(
        self,
        chroma_dir: Path = CHROMA_DIR,
        collection_name: str = COLLECTION_NAME,
        model_name: str = MODEL_NAME,
    ):
        self.chroma_dir = Path(chroma_dir)
        self.collection_name = collection_name
        self.model_name = model_name
        self._client = None
        self._collection = None
        self._embedding_fn = None

    @property
    def collection(self):
        """Lazy: inicializa la conexion al vector store al primer uso."""
        if self._collection is None:
            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self.model_name
            )
            self._client = chromadb.PersistentClient(path=str(self.chroma_dir))
            self._collection = self._client.get_collection(
                name=self.collection_name,
                embedding_function=self._embedding_fn,
            )
        return self._collection

    def close(self) -> None:
        """Libera la referencia a la collection / driver."""
        self._collection = None
        self._client = None
        self._embedding_fn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def buscar(
        self,
        query: str,
        k: int = 5,
        proveedor_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Busca los chunks mas relevantes para una pregunta en lenguaje natural.

        La busqueda es SEMANTICA: el sistema convierte tu query en un embedding
        y recupera los chunks mas cercanos por distancia coseno. No es necesario
        que las palabras exactas aparezcan en los chunks - el modelo entiende
        sinonimos y contexto.

        Ejemplos:
            "MOQ tipico desde China"
              -> recupera chunks que mencionan pedido minimo aunque digan
                 "minimum order quantity" o "pedido base".

            "condiciones de pago"
              -> recupera chunks sobre payment terms, T/T deposit, plazos.

            "lead time productos navidenos India"
              -> recupera chunks sobre tiempos de entrega de Mumbai Artisan.

        Args:
            query: pregunta o frase de busqueda en lenguaje natural.
            k: cantidad maxima de resultados. Default 5.
            proveedor_id: si se proporciona, restringe la busqueda a chunks
                          cuyo metadata.proveedor_id sea exactamente ese
                          valor. Ej: "SUP-01" para solo buscar en DALIAN_MIRO.
                          None para buscar en todos los catalogos.

        Returns:
            Lista de dicts ordenada por relevancia (mas relevante primero).
            Cada dict contiene:
              - texto: el contenido del chunk
              - score: similitud (entre 0 y 1, mayor = mas relevante)
              - proveedor_id: id del proveedor del catalogo (ej: "SUP-01")
              - proveedor_nombre: nombre legible (ej: "DALIAN_MIRO")
              - source: nombre del archivo PDF original
              - chunk_index: posicion del chunk dentro del PDF

            Si proveedor_id no existe en el indice, devuelve [].
        """
        where = {"proveedor_id": proveedor_id} if proveedor_id else None
        result = self.collection.query(
            query_texts=[query],
            n_results=k,
            where=where,
        )

        # ChromaDB devuelve listas de listas (porque acepta multiples queries).
        # Como mandamos una sola query, accedemos al indice [0].
        docs = (result.get("documents") or [[]])[0]
        metas = (result.get("metadatas") or [[]])[0]
        distancias = (result.get("distances") or [[]])[0]

        salida = []
        for texto, meta, dist in zip(docs, metas, distancias):
            salida.append({
                "texto": texto,
                "score": round(1.0 - float(dist), 4),  # cos similarity ~ 1 - cos distance
                "proveedor_id": meta.get("proveedor_id"),
                "proveedor_nombre": meta.get("proveedor_nombre"),
                "source": meta.get("source"),
                "chunk_index": meta.get("chunk_index"),
            })
        return salida

    def proveedores_indexados(self) -> list[dict]:
        """
        Lista los proveedores cuyos catalogos estan actualmente indexados,
        con la cantidad de chunks por cada uno.

        Util para que el operador o agentes vean que data esta disponible
        antes de hacer una consulta.

        Returns:
            Lista de dicts con proveedor_id, proveedor_nombre, cantidad_chunks.
        """
        # Traemos todos los metadatos (sin filtros) para agregar.
        # ChromaDB no expone group-by nativamente, agregamos en Python.
        all_data = self.collection.get(include=["metadatas"])
        metas = all_data.get("metadatas") or []
        agregado = {}
        for m in metas:
            key = (m.get("proveedor_id"), m.get("proveedor_nombre"))
            agregado[key] = agregado.get(key, 0) + 1
        return [
            {
                "proveedor_id": pid,
                "proveedor_nombre": pname,
                "cantidad_chunks": cnt,
            }
            for (pid, pname), cnt in sorted(agregado.items(), key=lambda x: -x[1])
        ]
