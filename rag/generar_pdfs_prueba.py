"""
generar_pdfs_prueba.py
-----------------------
Genera 3 PDFs ficticios de catalogos de proveedores navidenos
para probar el pipeline del RAG mientras conseguimos catalogos reales.
Tarea 1 - Bloque 7.

Los PDFs se guardan en data/catalogos_pdf/ y simulan estilos distintos:
  - Importadora del Este (paraguayo, formal)
  - Yiwu Christmas Trading (chino, conciso, MOQ alto)
  - Dulces del Plata (argentino, foco en alimentos perecederos)

NOTA: el contenido es ficticio. Estos PDFs son solo para validar
que el pipeline de RAG funciona. Despues se reemplazan por catalogos
reales que entregue el equipo de compras.
"""

from pathlib import Path
from fpdf import FPDF


SALIDA = Path(__file__).parent.parent / "data" / "catalogos_pdf"


# Catalogo 1: proveedor paraguayo formal
CATALOGO_IMPORTADORA_DEL_ESTE = """
CATALOGO TEMPORADA NAVIDAD 2026
Importadora del Este SA - RUC 80012345-6
Ciudad del Este, Paraguay
contacto@importadoradeleste.com.py

Estimado cliente, ponemos a su disposicion nuestra linea navidena 2026,
con productos seleccionados de fabricantes europeos y asiaticos.

CONDICIONES COMERCIALES GENERALES:
- Pedido minimo (MOQ) por SKU: 50 unidades
- Tiempo de entrega (lead time): 7 dias habiles desde confirmacion
- Forma de pago: 50 por ciento contra factura, 50 por ciento a 30 dias
- Moneda: guaranies o dolares americanos al cambio del dia
- Descuentos por volumen escalonados:
  * 50 a 99 unidades por SKU: 5 por ciento de descuento
  * 100 a 199 unidades por SKU: 10 por ciento
  * 200 unidades o mas: 15 por ciento

LINEA DE ARBOLES NAVIDENOS
Arboles artificiales premium importados, base metalica incluida,
ramas tipo PVC con efecto realista. Garantia de 2 temporadas.

- Modelo PREMIUM 1.80m, 800 ramas, color verde clasico:
  Precio unitario referencia 180.000 PYG. SKU sugerido: ARB-PREM-180.

- Modelo PREMIUM 2.10m, 1100 ramas, color verde clasico:
  Precio unitario referencia 250.000 PYG. SKU sugerido: ARB-PREM-210.

- Modelo MINI 60cm para mesa, ramas verdes con nieve artificial:
  Precio unitario referencia 75.000 PYG. SKU sugerido: ARB-MINI-60.

LINEA DE LUCES Y GUIRNALDAS
Luces LED de bajo consumo, tension 220V, certificacion CE.

- Guirnalda LED 100 luces multicolor 10 metros: 28.000 PYG por unidad.
- Guirnalda LED 200 luces blanco calido 20 metros: 32.000 PYG por unidad.

OBSERVACIONES IMPORTANTES:
Los pedidos para temporada navidena deben confirmarse antes del 15 de octubre
para garantizar entrega en tiempo. Despues de esa fecha el lead time puede
extenderse hasta 21 dias por congestion en aduana.

Los productos no son perecederos. Para devoluciones por defecto de fabrica
contactar dentro de los primeros 15 dias post entrega.
"""


# Catalogo 2: proveedor chino, mas conciso, MOQ alto
CATALOGO_YIWU = """
YIWU CHRISTMAS TRADING CO. LTD
Catalogue Christmas Season 2026 - Spanish version

DIRECCION: Yiwu International Trade City, Zhejiang, China.
EMAIL: sales@yiwuchristmas.cn

CONDICIONES GENERALES (MUY IMPORTANTE LEER):

Pedido minimo por SKU (MOQ) es alto debido a produccion en escala:
- Productos pequenos (esferas, adornos, luces): MOQ 500 unidades.
- Productos medianos (arboles mini, figuras): MOQ 300 unidades.
- Productos grandes (arboles 1.80m o mas): MOQ 200 unidades.

Lead time desde Yiwu a Asuncion via maritimo:
- 45 dias habiles puerta a puerta.
- En promedio 35 dias navegacion + 10 dias aduana paraguay.

Forma de pago: 30 por ciento adelanto T/T, 70 por ciento contra B/L copia.

Descuentos por volumen muy agresivos:
- 500-999 unidades: 15 por ciento off precio FOB.
- 1000-2999 unidades: 20 por ciento off precio FOB.
- 3000 unidades o mas: 25 por ciento off precio FOB.

PRODUCTOS DESTACADOS NAVIDAD 2026:

ESFERAS Y ADORNOS:
- Set 24 esferas color dorado clasico, 8cm: USD 3.50 por set FOB Yiwu.
- Set 24 esferas multicolor variadas: USD 3.80 por set FOB Yiwu.
- Estrella punta de arbol con luces LED incorporadas: USD 1.20 unidad.

LUCES LED:
- Guirnalda 100 LED multicolor: USD 1.80 unidad FOB.
- Guirnalda 200 LED blanco calido: USD 2.50 unidad FOB.

ARBOLES ARTIFICIALES:
- Arbol 1.80m verde, 800 ramas, base metalica: USD 12.00 unidad FOB.
- Arbol 2.10m verde, 1100 ramas, base metalica: USD 17.00 unidad FOB.

NOTAS COMERCIALES:
Para el calendario 2026 sugerimos confirmar pedidos antes de fines de agosto
para asegurar arribo en Paraguay antes del 1 de noviembre. Pedidos
posteriores no garantizamos llegada antes de Black Friday.

No realizamos envios urgentes via aereo salvo casos excepcionales y bajo
sobrecosto a discutir.
"""


# Catalogo 3: proveedor argentino, alimentos perecederos
CATALOGO_DULCES_DEL_PLATA = """
DULCES DEL PLATA - PANIFICADOS Y CONFITERIA
Buenos Aires, Argentina | RUC argentino 30-71234567-8
ventas@dulcesdelplata.com.ar

Catalogo Navidad 2026 - Linea Panettones, Turrones y Confituras

QUIENES SOMOS:
Empresa familiar con 30 anos de tradicion en la produccion de panettones
y dulces navidenos artesanales. Distribuimos en Argentina, Paraguay,
Uruguay y Bolivia. Productos elaborados con ingredientes naturales,
sin conservantes artificiales.

CONDICIONES COMERCIALES PARA PARAGUAY:

PEDIDO MINIMO (MOQ): 30 unidades por SKU. Pedidos menores no se procesan.

LEAD TIME: 10 dias habiles desde confirmacion hasta entrega en deposito
de la importadora en Asuncion. Incluye despacho aduanero y refrigeracion.

PERECEDEROS - ATENCION:
Todos nuestros productos son alimentos con vencimiento. Es CRITICO
que la importadora respete las condiciones de almacenaje:
- Temperatura entre 18 y 22 grados.
- Humedad relativa menor a 65 por ciento.
- Lejos de fuentes de luz solar directa.

VIDA UTIL DESDE FABRICACION:
- Panettones tradicionales: 90 dias.
- Panettones con chocolate: 75 dias.
- Turrones: 180 dias.
- Garrapinada y confituras: 120 dias.

LINEA PANETTONES:
- Panettone tradicional 750g con frutas confitadas: ARS 4.500 unidad.
- Panettone con chocolate 500g: ARS 5.200 unidad.
- Panettone gourmet edicion limitada 1kg: ARS 8.900 unidad.

LINEA TURRONES:
- Turron de almendras 200g: ARS 2.300 unidad.
- Turron de mani con chocolate 150g: ARS 1.800 unidad.

DESCUENTOS POR VOLUMEN:
- 30-99 unidades: precio de lista.
- 100-299 unidades: 8 por ciento descuento.
- 300 unidades o mas: 12 por ciento descuento.

FORMA DE PAGO:
Contado contra factura, o 50 por ciento adelanto y 50 por ciento a 30 dias
con orden de compra firmada.

CALENDARIO RECOMENDADO PARA TEMPORADA 2026:
Confirmar pedidos antes del 30 de septiembre. Despues de esa fecha
producimos sobre demanda y los plazos se duplican.
"""


def generar_pdf(titulo: str, contenido: str, nombre_archivo: str):
    """Genera un PDF simple con el contenido dado."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Titulo
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, titulo, ln=True, align="C")
    pdf.ln(5)

    # Contenido
    pdf.set_font("Helvetica", size=10)
    for linea in contenido.strip().split("\n"):
        # Cell con texto multilinea
        if linea.strip():
            pdf.multi_cell(0, 5, linea.strip())
        else:
            pdf.ln(3)

    ruta = SALIDA / nombre_archivo
    pdf.output(str(ruta))
    return ruta


def main():
    SALIDA.mkdir(parents=True, exist_ok=True)
    print(f"Generando PDFs de prueba en: {SALIDA}\n")

    catalogos = [
        ("CATALOGO IMPORTADORA DEL ESTE - NAVIDAD 2026",
         CATALOGO_IMPORTADORA_DEL_ESTE,
         "catalogo_importadora_del_este_2026.pdf"),
        ("YIWU CHRISTMAS TRADING - CATALOGUE 2026",
         CATALOGO_YIWU,
         "catalogo_yiwu_christmas_2026.pdf"),
        ("DULCES DEL PLATA - CATALOGO NAVIDAD 2026",
         CATALOGO_DULCES_DEL_PLATA,
         "catalogo_dulces_del_plata_2026.pdf"),
    ]

    for titulo, contenido, nombre in catalogos:
        ruta = generar_pdf(titulo, contenido, nombre)
        print(f"  Generado: {ruta.name}  ({ruta.stat().st_size:,} bytes)")

    print(f"\n{len(catalogos)} catalogos generados en data/catalogos_pdf/.")
    print("Estos PDFs simulan catalogos reales para probar el pipeline del RAG.")


if __name__ == "__main__":
    main()
