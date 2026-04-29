"""
rag/ingesta.py
---------------
Pipeline de ingesta del RAG sobre catalogos de proveedores.
Tarea 1 - Bloque 7.

Lo que hace:
  1. Lee todos los PDFs de data/catalogos_pdf/.
  2. Extrae el texto de cada uno.
  3. Trocea el texto en chunks de ~800 caracteres con overlap de 100.
  4. Genera embeddings semanticos (modelo multilingue, entiende español).
  5. Guarda los chunks en ChromaDB persistente con metadatos
     (proveedor_id, source, chunk_index) para que las busquedas se puedan
     filtrar por proveedor.

Es idempotente (usa upsert): re-correrlo NO duplica chunks.

Para agregar mas catalogos: simplemente droppealos en data/catalogos_pdf/
y volve a correr este script.
"""

import re
from pathlib import Path

from pypdf import PdfReader
import chromadb
from chromadb.utils import embedding_functions


# Configuracion
# La carpeta de catalogos vive bajo data/CATALOGOS. Si queres agregar mas
# catalogos, simplemente droppealos ahi (PDF) y volve a correr este script.
PDF_DIR = Path(__file__).parent.parent / "data" / "CATALOGOS"
CHROMA_DIR = Path(__file__).parent.parent / "chroma_db"
COLLECTION_NAME = "catalogos_proveedores"

CHUNK_SIZE = 800       # caracteres por chunk
CHUNK_OVERLAP = 100    # solapamiento para no perder contexto en bordes

# Modelo de embeddings multilingue (~120MB, descarga la primera vez).
# Buena calidad para español, rapido en CPU.
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"


def extraer_texto(ruta_pdf: Path) -> str:
    """Extrae todo el texto de un PDF concatenando sus paginas."""
    reader = PdfReader(str(ruta_pdf))
    paginas = []
    for page in reader.pages:
        text = page.extract_text() or ""
        paginas.append(text)
    return "\n\n".join(paginas)


def chunk_texto(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Divide un texto en chunks superpuestos por caracteres.
    El overlap evita perder el contexto en los bordes entre chunks.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks = []
    start = 0
    step = size - overlap
    while start < len(text):
        end = start + size
        fragmento = text[start:end].strip()
        if fragmento:
            chunks.append(fragmento)
        start += step
    return chunks


def proveedor_desde_archivo(nombre_archivo: str) -> tuple[str, str]:
    """
    Deriva (proveedor_id, proveedor_nombre) desde el nombre del archivo PDF.

    Soporta dos formatos:
      - 'Catalogo_Proveedor_1_DALIAN_MIRO.pdf' -> ('SUP-01', 'DALIAN_MIRO')
        (formato de los catalogos sinteticos en data/CATALOGOS)
      - 'catalogo_importadora_del_este_2026.pdf' -> ('importadora_del_este',
        'importadora_del_este')
        (formato legacy)

    Cuando se reemplacen los catalogos sinteticos por reales de Marketplace,
    actualizar esta funcion para mapear filename -> COD_PROVEEDOR de Pegasus.
    """
    base = Path(nombre_archivo).stem

    # Formato sintetico: "Catalogo_Proveedor_<numero>_<NOMBRE>"
    match = re.match(r"^Catalogo_Proveedor_(\d+)_(.+)$", base, flags=re.IGNORECASE)
    if match:
        numero = int(match.group(1))
        nombre = match.group(2).strip()
        proveedor_id = f"SUP-{numero:02d}"  # SUP-01, SUP-02, ...
        return proveedor_id, nombre

    # Formato legacy "catalogo_<nombre>_<año>"
    base = re.sub(r"^catalogo_?", "", base, flags=re.IGNORECASE)
    base = re.sub(r"_\d{4}$", "", base)
    return base, base


def main():
    if not PDF_DIR.exists() or not list(PDF_DIR.glob("*.pdf")):
        print(f"No hay PDFs en {PDF_DIR}.")
        print("Corre primero: python rag\\generar_pdfs_prueba.py")
        print("(o droppea catalogos PDF reales en esa carpeta)")
        return

    print(f"Cargando modelo de embeddings: {MODEL_NAME}")
    print("(la primera vez descarga ~120MB, puede tardar 1-2 min)\n")
    embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=MODEL_NAME
    )

    chroma = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # Metric coseno: el natural para embeddings de sentence-transformers.
    # Sin este metadata, Chroma usa L2 (euclideana cuadrada) y los "scores"
    # 1 - distance dan numeros negativos no interpretables.
    collection = chroma.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )

    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    print(f"{len(pdfs)} PDF(s) detectado(s) en {PDF_DIR}:\n")

    total_chunks = 0
    for pdf_path in pdfs:
        proveedor_id, proveedor_nombre = proveedor_desde_archivo(pdf_path.name)
        print(f"  Procesando: {pdf_path.name}")
        print(f"    proveedor_id: {proveedor_id}  nombre: {proveedor_nombre}")

        texto = extraer_texto(pdf_path)
        if not texto.strip():
            print(f"    Sin texto extraible (PDF vacio o solo imagenes). Salto.")
            continue

        chunks = chunk_texto(texto)
        if not chunks:
            print(f"    No se generaron chunks. Salto.")
            continue

        # IDs deterministas: si re-corremos sobre el mismo PDF, upsert reemplaza.
        ids = [f"{pdf_path.stem}__{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "proveedor_id": proveedor_id,
                "proveedor_nombre": proveedor_nombre,
                "source": pdf_path.name,
                "chunk_index": i,
            }
            for i in range(len(chunks))
        ]

        collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)
        print(f"    {len(chunks)} chunks ingestados (~{len(texto):,} caracteres)")
        total_chunks += len(chunks)

    print(f"\n=== Ingesta completa ===")
    print(f"  Chunks procesados en esta corrida: {total_chunks}")
    print(f"  Total documentos en collection '{COLLECTION_NAME}': {collection.count()}")
    print(f"  Vector store persistido en: {CHROMA_DIR}")


if __name__ == "__main__":
    main()
