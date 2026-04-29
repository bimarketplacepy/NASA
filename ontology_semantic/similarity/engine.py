"""engine.py - SimilarityEngine: scorers + composite.

Tarea 1 v2 - Bloque 5 - Stage 3.

Esta clase NO computa embeddings ni Gower-matrix masivamente: para eso
estan ``embeddings.py`` (precompute one-shot) y ``precompute.py`` (matriz
top-K). ``SimilarityEngine`` opera par-a-par usando los artefactos
ya persistidos: matriz numpy de embeddings, indice SKU->fila, y dict
de atributos categoricos por SKU.

Diseno: el motor recibe en el constructor todos los datos derivados
ya cargados (embeddings, atributos categoricos, etc.). Esto:

1. Mantiene la clase testeable (en tests inyectamos fixtures pequenios).
2. Evita re-cargar 4643 vectores en cada query.
3. Hace explicito el contrato: "para usarme, primero corres
   ``precompute_embeddings`` y ``load_structural_attributes``".

El ``composite_score`` detecta automaticamente cuando un scorer reporta
missing y RENORMALIZA los pesos restantes. Asi un par cold-start
(behavioral missing) sigue dando una similitud significativa con el
peso del lexical+structural+trend redistribuido. ``confidence`` refleja
la suma de pesos efectivamente usados ANTES de renormalizar.

Construccion conveniente desde disco (post Stage 2 + Stage 4):

    eng = SimilarityEngine.from_disk()           # carga embeddings + attrs
    res = eng.composite_score("247329", "215773")
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

import numpy as np

from ontology_semantic.similarity.config import (
    SimilarityConfig,
    load_config,
)
from ontology_semantic.similarity.types import (
    BehavioralFlag,
    SimilarityResult,
)


# Tipo del callable que embeddea texto en runtime. Devuelve un vector
# normalizado L2 (norma 1) de dim = cfg.embedding_dim.
EmbedFn = Callable[[str], np.ndarray]


class SimilarityEngine:
    """Motor par-a-par que combina lexical + structural + behavioral + trend.

    Los datos derivados (matriz de embeddings, atributos categoricos por
    SKU, etc.) se inyectan en el constructor. Esto convierte la clase
    en algo trivialmente testeable sin Neo4j ni el modelo cargado.

    Args:
        cfg: configuracion cargada via :func:`load_config`.
        embeddings: matriz ``(N, dim)`` numpy float32 con embeddings de
            texto, normalizada L2 (norma 1). ``None`` si todavia no se
            computaron (en cuyo caso ``score_lexical`` lanza error claro).
        sku_to_row: dict que mapea SKU (str) a indice de fila en la
            matriz ``embeddings``.
        attrs_by_sku: dict ``sku -> dict[attr_name, value]`` con los
            atributos categoricos para Gower estructural.
        monthly_sales_by_sku: dict ``sku -> np.ndarray`` con vector
            mensual de ventas. ``None`` o vacio si no hay datos (Bloque 5
            arranca asi para todos los SKUs).
        trend_signal_text: texto consolidado de TrendSignals activos
            para usar en ``score_trend``. ``None`` o ``""`` si no hay
            senales.
        embed_fn: callable que embeddea texto en runtime. Si es ``None``,
            se carga sentence-transformers la primera vez que se necesite
            (lazy). Tests inyectan un fake aqui.
    """

    def __init__(
        self,
        cfg: SimilarityConfig,
        embeddings: Optional[np.ndarray] = None,
        sku_to_row: Optional[dict[str, int]] = None,
        attrs_by_sku: Optional[dict[str, dict[str, object]]] = None,
        monthly_sales_by_sku: Optional[dict[str, np.ndarray]] = None,
        trend_signal_text: Optional[str] = None,
        embed_fn: Optional[EmbedFn] = None,
    ) -> None:
        self.cfg = cfg
        self.embeddings = embeddings
        self.sku_to_row = sku_to_row or {}
        self.attrs_by_sku = attrs_by_sku or {}
        self.monthly_sales_by_sku = monthly_sales_by_sku or {}
        self.trend_signal_text = (trend_signal_text or "").strip()
        self._embed_fn = embed_fn  # lazy loader si es None

        # Cache de embeddings de texto en runtime (trend signals,
        # descripciones de cold-start). Limita el costo cuando se llama
        # con el mismo texto repetidamente.
        self._text_emb_cache: dict[str, np.ndarray] = {}

    # =========================================================================
    # Construccion conveniente desde disco.
    # =========================================================================

    @classmethod
    def from_disk(
        cls,
        cfg: Optional[SimilarityConfig] = None,
        npy_path: Optional[Path] = None,
        index_path: Optional[Path] = None,
        trend_signal_text: Optional[str] = None,
    ) -> "SimilarityEngine":
        """Carga embeddings + atributos persistidos y devuelve un engine listo.

        Lee ``data/embeddings_productos.npy`` + ``data/embeddings_index.json``
        (producidos por :func:`embeddings.precompute_embeddings`) y arma
        el dict ``attrs_by_sku`` directamente desde el index.

        Args:
            cfg: SimilarityConfig. Si ``None`` carga el default.
            npy_path: ruta de la matriz. ``None`` usa el default.
            index_path: ruta del index JSON. ``None`` usa el default.
            trend_signal_text: texto consolidado de TrendSignals para
                ``score_trend``. ``None`` arranca sin senales.

        Returns:
            :class:`SimilarityEngine` con embeddings + attrs cargados.

        Raises:
            FileNotFoundError: si los archivos persistidos no existen.
        """
        # Import diferido para evitar ciclos en Stage 1.
        from ontology_semantic.similarity.embeddings import (
            EMBEDDINGS_INDEX,
            EMBEDDINGS_NPY,
            load_embeddings,
        )

        if cfg is None:
            cfg = load_config()
        if npy_path is None:
            npy_path = EMBEDDINGS_NPY
        if index_path is None:
            index_path = EMBEDDINGS_INDEX

        matrix, _, sku_to_row, productos, _ = load_embeddings(npy_path, index_path)
        attrs_by_sku = {p["sku"]: p["attrs"] for p in productos}
        return cls(
            cfg=cfg,
            embeddings=matrix,
            sku_to_row=sku_to_row,
            attrs_by_sku=attrs_by_sku,
            trend_signal_text=trend_signal_text,
        )

    # =========================================================================
    # Embedding helper (lazy load del modelo).
    # =========================================================================

    def _ensure_embed_fn(self) -> EmbedFn:
        """Devuelve la funcion de embedding, cargando el modelo si hace falta.

        El modelo se carga UNA sola vez por instancia (lazy). Subsiguientes
        llamadas reusan la misma instancia. Si el caller paso ``embed_fn``
        en el constructor (tests), se usa ese sin cargar nada.
        """
        if self._embed_fn is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self.cfg.embedding_model_name)
            expected_dim = self.cfg.embedding_dim

            def _fn(text: str) -> np.ndarray:
                v = model.encode(
                    [text],
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )[0]
                v = v.astype(np.float32)
                if v.shape[0] != expected_dim:
                    raise RuntimeError(
                        f"embed_fn devolvio dim={v.shape[0]}, "
                        f"esperaba {expected_dim}"
                    )
                return v

            self._embed_fn = _fn
        return self._embed_fn

    def embed_text(self, text: str) -> np.ndarray:
        """Embeddea un texto arbitrario con el mismo modelo del catalogo.

        Cachea por texto exacto para evitar re-embeddear en batch.

        Args:
            text: texto a embeddear (ej. "esfera dorada navidena 8cm").

        Returns:
            Vector ``(dim,)`` float32 normalizado L2.
        """
        key = text.strip()
        if key in self._text_emb_cache:
            return self._text_emb_cache[key]
        fn = self._ensure_embed_fn()
        v = fn(key)
        self._text_emb_cache[key] = v
        return v

    # =========================================================================
    # Scorers individuales.
    # =========================================================================

    def score_lexical(self, sku_a: str, sku_b: str) -> float:
        """Cosine sobre embeddings de texto entre dos SKUs.

        Como los embeddings persistidos estan normalizados L2, el cosine
        es exactamente el producto punto: ``cos(a, b) = a . b``. Mas
        rapido que computar normas en runtime.

        Args:
            sku_a: codigo del primer SKU. Debe estar en ``sku_to_row``.
            sku_b: codigo del segundo SKU. Debe estar en ``sku_to_row``.

        Returns:
            Similitud coseno clipeada a ``[0, 1]``. ``1.0`` si
            ``sku_a == sku_b``.

        Raises:
            RuntimeError: si la matriz de embeddings no fue inyectada.
            KeyError: si alguno de los SKUs no esta en ``sku_to_row``.
        """
        if sku_a == sku_b:
            return 1.0
        if self.embeddings is None:
            raise RuntimeError(
                "score_lexical: la matriz de embeddings no fue inyectada. "
                "Usa from_disk() o pasa embeddings al constructor."
            )
        if sku_a not in self.sku_to_row:
            raise KeyError(f"SKU {sku_a!r} no esta en sku_to_row")
        if sku_b not in self.sku_to_row:
            raise KeyError(f"SKU {sku_b!r} no esta en sku_to_row")

        ra = self.sku_to_row[sku_a]
        rb = self.sku_to_row[sku_b]
        # Producto punto (cosine porque ambos vectores son unitarios).
        val = float(np.dot(self.embeddings[ra], self.embeddings[rb]))
        # Por errores de precision puede ligeramente pasar [-1, 1] o ser
        # negativo (raro en este dominio); clipeamos a [0, 1].
        return float(np.clip(val, 0.0, 1.0))

    def score_structural(self, sku_a: str, sku_b: str) -> float:
        """Distancia de Gower invertida sobre atributos categoricos.

        Para cada atributo definido en ``cfg.structural_attributes``:
        - Si alguno de los SKUs no tiene el atributo (None / ""),
          se EXCLUYE del promedio (semantica Gower nativa).
        - Si ambos lo tienen, contribuye con su peso interno: ``1.0 * w``
          si son iguales, ``0.0 * w`` si distintos.

        El score final es ``sum(matches * w) / sum(w_disponibles)``.

        Args:
            sku_a: primer SKU.
            sku_b: segundo SKU.

        Returns:
            Similitud estructural en ``[0, 1]``. ``1.0`` si
            ``sku_a == sku_b``. ``0.0`` si ningun atributo es comparable
            (ej. uno de los SKUs no esta en ``attrs_by_sku``).
        """
        if sku_a == sku_b:
            return 1.0

        a = self.attrs_by_sku.get(sku_a)
        b = self.attrs_by_sku.get(sku_b)
        if not a or not b:
            return 0.0

        sum_w = 0.0
        sum_match = 0.0
        for attr in self.cfg.structural_attributes:
            va = a.get(attr.name)
            vb = b.get(attr.name)
            # Excluir atributos faltantes - Gower nativo.
            if va is None or vb is None or va == "" or vb == "":
                continue
            match = 1.0 if va == vb else 0.0
            sum_match += match * attr.weight
            sum_w += attr.weight

        if sum_w == 0.0:
            return 0.0
        return sum_match / sum_w

    def score_behavioral(
        self,
        sku_a: str,
        sku_b: str,
    ) -> tuple[float, BehavioralFlag]:
        """Cosine sobre vector de ventas mensuales.

        En el Bloque 5 inicial este metodo SIEMPRE retorna
        ``(0.0, UNAVAILABLE_GLOBAL)`` porque la fuente VENTAS_DET por
        mes no esta integrada todavia. Cuando ``cfg.behavioral_available``
        sea ``True`` y ``monthly_sales_by_sku`` tenga datos, la logica
        cosine se activa.

        Args:
            sku_a: primer SKU.
            sku_b: segundo SKU.

        Returns:
            Tupla ``(score, flag)``. ``score`` es ``0.0`` si ``flag``
            indica missing.
        """
        if not self.cfg.behavioral_available:
            return 0.0, BehavioralFlag.UNAVAILABLE_GLOBAL

        sa = self.monthly_sales_by_sku.get(sku_a)
        sb = self.monthly_sales_by_sku.get(sku_b)
        a_missing = sa is None or len(sa) == 0
        b_missing = sb is None or len(sb) == 0
        if a_missing and b_missing:
            return 0.0, BehavioralFlag.MISSING_BOTH
        if a_missing:
            return 0.0, BehavioralFlag.MISSING_A
        if b_missing:
            return 0.0, BehavioralFlag.MISSING_B

        sa = np.asarray(sa, dtype=np.float32)
        sb = np.asarray(sb, dtype=np.float32)
        na = float(np.linalg.norm(sa))
        nb = float(np.linalg.norm(sb))
        if na == 0 and nb == 0:
            return 0.0, BehavioralFlag.MISSING_BOTH
        if na == 0:
            return 0.0, BehavioralFlag.MISSING_A
        if nb == 0:
            return 0.0, BehavioralFlag.MISSING_B

        val = float(np.dot(sa, sb) / (na * nb))
        return float(np.clip(val, 0.0, 1.0)), BehavioralFlag.AVAILABLE

    def score_trend(
        self,
        sku: str,
        trend_signal: Optional[str] = None,
    ) -> float:
        """Similitud lexica entre la descripcion del SKU y un trend signal.

        Reusa el embedding precomputado del SKU (norma 1) y embeddea el
        ``trend_signal`` en runtime con el mismo modelo (cacheado).
        Cosine = producto punto porque ambos son unitarios.

        Args:
            sku: codigo del SKU a comparar contra la senal.
            trend_signal: texto del trend. Si ``None``, usa
                ``self.trend_signal_text`` (consolidado al instanciar).

        Returns:
            Similitud coseno en ``[0, 1]``. ``0.0`` si no hay trend
            signal disponible o el SKU no esta en ``sku_to_row`` o si
            no hay matriz de embeddings.
        """
        text = (trend_signal if trend_signal is not None
                else self.trend_signal_text)
        if not text or not text.strip():
            return 0.0
        if self.embeddings is None or sku not in self.sku_to_row:
            return 0.0

        sku_emb = self.embeddings[self.sku_to_row[sku]]
        trend_emb = self.embed_text(text)
        val = float(np.dot(sku_emb, trend_emb))
        return float(np.clip(val, 0.0, 1.0))

    # =========================================================================
    # Composite con renormalizacion.
    # =========================================================================

    def _trend_disponible(self) -> bool:
        return bool(self.trend_signal_text and self.trend_signal_text.strip())

    def _structural_disponible(self, sku_a: str, sku_b: str) -> bool:
        return (sku_a in self.attrs_by_sku
                and sku_b in self.attrs_by_sku
                and bool(self.attrs_by_sku[sku_a])
                and bool(self.attrs_by_sku[sku_b]))

    def composite_score(
        self,
        sku_a: str,
        sku_b: str,
        weights_override: Optional[dict[str, float]] = None,
    ) -> SimilarityResult:
        """Combina los 4 scorers en un score ponderado renormalizado.

        Algoritmo:

        1. Si ``sku_a == sku_b``, atajo: score 1.0 con confidence 1.0.
        2. Calcula los 4 scorers individuales.
        3. Determina disponibilidad de cada uno:
           - lexical: disponible si ambos SKUs estan en ``sku_to_row``.
           - structural: disponible si ambos estan en ``attrs_by_sku``.
           - behavioral: disponible si ``flag == AVAILABLE``.
           - trend: disponible si ``trend_signal_text`` no es vacio.
        4. ``confidence`` = suma de pesos de scorers disponibles
           (antes de renormalizar). Es la senal honesta para el dispatcher.
        5. Pesos efectivos = pesos disponibles re-escalados a sumar 1.
        6. ``score_total`` = combinacion lineal con pesos efectivos.

        Args:
            sku_a: primer SKU.
            sku_b: segundo SKU.
            weights_override: dict opcional para override por query.
                Misma estructura que ``cfg.weights``. Pesos no provistos
                heredan del cfg.

        Returns:
            :class:`SimilarityResult` con todos los scorers individuales
            + composite + confidence + flags.
        """
        if sku_a == sku_b:
            return SimilarityResult(
                sku_a=sku_a, sku_b=sku_b,
                score_lexical=1.0, score_structural=1.0,
                score_behavioral=1.0, score_trend=1.0,
                score_total=1.0, confidence=1.0,
                behavioral_flag=BehavioralFlag.AVAILABLE,
                flags=("identity",),
            )

        # Pesos efectivos (defaults del YAML, posibles overrides).
        weights = dict(self.cfg.weights)
        if weights_override:
            for k, v in weights_override.items():
                if k not in weights:
                    raise ValueError(
                        f"weights_override contiene clave desconocida: {k!r}. "
                        f"Validas: {sorted(weights.keys())}"
                    )
                if v < 0:
                    raise ValueError(
                        f"weights_override[{k!r}]={v} debe ser >= 0"
                    )
                weights[k] = float(v)

        # 1. Computar scorers.
        s_lex = self.score_lexical(sku_a, sku_b)
        s_str = self.score_structural(sku_a, sku_b)
        s_beh, beh_flag = self.score_behavioral(sku_a, sku_b)
        s_trd = self.score_trend(sku_a)  # vs trend_signal_text global

        # 2. Disponibilidad por scorer + flags textuales.
        flags: list[str] = []
        disponibles: dict[str, float] = {"lexical": weights["lexical"]}

        if self._structural_disponible(sku_a, sku_b):
            disponibles["structural"] = weights["structural"]
        else:
            flags.append("structural_missing")

        if beh_flag == BehavioralFlag.AVAILABLE:
            disponibles["behavioral"] = weights["behavioral"]
        else:
            # Flags por sub-tipo para que el dispatcher pueda inspeccionar.
            flags.append(f"behavioral_{beh_flag.value}")

        if self._trend_disponible():
            disponibles["trend"] = weights["trend"]
        else:
            flags.append("trend_no_signal")

        # 3. Confidence = suma de pesos de scorers disponibles
        #    (ANTES de renormalizar - eso es la senal cruda).
        confidence = float(sum(disponibles.values()))
        # Si los pesos del YAML suman 1.0, esto queda en [0, 1].
        # Por seguridad clipeamos: pesos custom podrian sumar > 1.
        confidence_clip = float(np.clip(confidence, 0.0, 1.0))

        # 4. Renormalizar para que sumen 1 -> pesos efectivos.
        if confidence > 0:
            eff = {k: v / confidence for k, v in disponibles.items()}
        else:
            eff = {}

        # 5. Composite.
        score_total = (
            eff.get("lexical", 0.0) * s_lex
            + eff.get("structural", 0.0) * s_str
            + eff.get("behavioral", 0.0) * s_beh
            + eff.get("trend", 0.0) * s_trd
        )
        # Por errores de redondeo numerico.
        score_total = float(np.clip(score_total, 0.0, 1.0))

        return SimilarityResult(
            sku_a=sku_a, sku_b=sku_b,
            score_lexical=float(s_lex),
            score_structural=float(s_str),
            score_behavioral=float(s_beh),
            score_trend=float(s_trd),
            score_total=score_total,
            confidence=confidence_clip,
            behavioral_flag=beh_flag,
            flags=tuple(flags),
        )
