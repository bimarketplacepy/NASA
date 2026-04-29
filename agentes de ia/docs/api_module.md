# Routers HTTP iniciales

Se conectaron endpoints funcionales para probar flujo end-to-end:

- `GET /api/v1/health`
- `POST /api/v1/recomendaciones/generar`
- `GET /api/v1/recomendaciones/{recomendacion_id}`
- `POST /api/v1/contrafactual/natural-language`
- `GET /api/v1/grafo/causal/{recomendacion_id}`
- `GET /api/v1/perfil/{operador_id}`
- `POST /api/v1/perfil/feedback`

Estos endpoints usan servicios reales implementados y permiten iterar sobre
demo funcional mientras se completa el resto del contrato API.

## Cobertura ampliada (iteracion actual)

- `GET /api/v1/productos?categoria=&page=&size=`
- `GET /api/v1/productos/{sku}`
- `GET /api/v1/productos/{sku}/forecast?semanas=`
- `GET /api/v1/proveedores`
- `GET /api/v1/proveedores/{proveedor_id}`
- `GET /api/v1/inventario`
- `GET /api/v1/inventario/alertas`
- `GET /api/v1/eventos`

## Cobertura conversacional/agentes (iteracion actual)

- `POST /api/v1/chat`
- `GET /api/v1/chat/sesiones/{sesion_id}`
- `POST /api/v1/agentes/web-research`
- `POST /api/v1/agentes/tendencias`
- `POST /api/v1/agentes/critico/atacar`
- `POST /api/v1/feedback`

## Cobertura operativa adicional

- `POST /api/v1/simulacion/montecarlo`
- `POST /api/v1/negociacion/borrador`
- `GET /api/v1/traces/{recomendacion_id}`
