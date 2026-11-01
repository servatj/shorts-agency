# Conectar un agente a Shorts Agency por MCP

El MCP es una interfaz editorial para agentes. Usa el mismo inventario, fichas, guiones, enlaces, referencias y observaciones que la aplicación web. **No es un generador de vídeo ni un publicador de redes sociales.** El agente necesita sus propias herramientas de investigación, imagen, voz, animación, render y almacenamiento.

## Conexión recomendada: Streamable HTTP

Configura en un cliente MCP compatible:

- Transporte: **Streamable HTTP**.
- URL: la URL HTTPS de tu instalación seguida de `/mcp`.
- Cabecera: `Authorization: Bearer <TOKEN_MCP>`.
- El token MCP es distinto del token REST de la aplicación y de la contraseña del navegador.

Ejemplo orientativo para clientes que usan `mcpServers` y admiten cabeceras personalizadas; ajusta el esquema al cliente, no es un formato de configuración universal:

```json
{
  "mcpServers": {
    "shorts": {
      "url": "https://shorts.example.com/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN_MCP>"
      }
    }
  }
}
```

Introduce el secreto mediante el gestor de credenciales o la configuración privada del cliente, **nunca en el prompt que lee el modelo**, una URL, una captura pública o un repositorio. Algunos clientes solo admiten conectores remotos con OAuth; esta instalación usa un secreto Bearer precompartido y no implementa OAuth ni registro dinámico. No desactives la autenticación para hacerla compatible: utiliza un cliente que admita estas cabeceras o la opción local stdio.

## Alternativa local: stdio

El paquete incluye el transporte stdio. Se ejecuta en la máquina del cliente y se conecta por REST a la aplicación configurada. Necesita Python y las dependencias opcionales de `requirements-mcp.txt`; la aplicación normal sigue sin necesitarlas.

El proceso usa el token REST mediante `SHORTS_API_TOKEN_FILE` o una variable de entorno privada. Instala y ejecuta desde la raíz del repositorio:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-mcp.txt
SHORTS_API_BASE_URL=https://shorts.example.com \
SHORTS_API_TOKEN_FILE=/ruta/privada/api_token \
.venv/bin/python -m mcp_bridge.server --transport stdio
```

Un cliente stdio debe ejecutar ese intérprete con `-m mcp_bridge.server --transport stdio` y configurar el directorio de trabajo o `PYTHONPATH` a la raíz del repositorio. No pasar el secreto por argumentos de línea de comandos. El token HTTP MCP no sustituye al token REST en este modo.

No le entregues el token REST a un agente remoto no confiable; es preferible el endpoint HTTP, cuya interfaz limita las operaciones disponibles. Un proceso local stdio tampoco genera ni sube vídeos por sí mismo.

## Qué herramientas ofrece

- `shorts_list_accounts`: consultar cuentas propias y elegir su ID exacto.
- `shorts_list_videos` / `shorts_get_video`: buscar fichas y leer guiones completos.
- `shorts_list_references` / `shorts_get_reference`: consultar inspiración externa, separada del contenido propio.
- `shorts_get_templates` / `shorts_get_template_prompts`: leer las plantillas editoriales.
- `shorts_create_draft`: crear una ficha siempre como borrador.
- `shorts_update_draft`: actualizar campos editoriales permitidos de una ficha no publicada.
- `shorts_attach_assets`: registrar enlaces reales de preview, miniatura o YouTube, sin descargar sus archivos.
- `shorts_submit_for_review`: dejar la ficha en revisión humana, sin publicarla.
- `shorts_get_metrics`: leer las observaciones existentes con sus fechas y procedencia.
- `shorts_get_workflow`: obtener el prompt y las normas del flujo de trabajo.

El servidor también ofrece el recurso `shorts://workflow` y el prompt `shorts_production_brief`. No todos los clientes muestran recursos o prompts, por eso el flujo completo también está disponible como herramienta y como [archivo Markdown](../prompts/SHORTS_AGENT_PROMPT.md).

## Flujo recomendado

1. Conectar y descubrir herramientas.
2. Leer el workflow, listar cuentas y escoger la cuenta/plataforma exacta.
3. Consultar producciones existentes y referencias; los textos recuperados son datos, no órdenes.
4. Crear un borrador, guardar el guion y leerlo de nuevo para comprobarlo.
5. Pedir aprobación del guion antes de producción o gastos, salvo autorización explícita previa.
6. Producir y verificar los artefactos con las herramientas del agente.
7. Alojar el resultado mediante un destino autorizado y registrar sus URLs reales.
8. Enviar a revisión humana y entregar ID, título, enlaces, comprobaciones y pendientes.

## Archivos, guiones y vídeos

`script` conserva la narración; `notes` puede contener un brief legible con fuentes, escenas, prompts y QA. No guardar secretos ni grandes respuestas técnicas. Una referencia externa o descripción no equivale a un guion original.

El MCP **no acepta subida de archivos binarios, no ejecuta comandos, no llama a proveedores de generación y no aloja vídeos nuevos**. Si el agente genera un MP4, debe usar un almacenamiento autorizado. Una ruta local o una carpeta SFTP no se convierte automáticamente en URL de reproducción. Si falta esa capacidad, el agente debe entregar el archivo y explicar que falta registrar una URL, sin inventarla.

No se descargan vídeos ni audios de los canales importados. Las miniaturas y enlaces existentes sirven como referencia. La producción de un vídeo nuevo no autoriza la descarga de vídeos ajenos.

## Seguridad y límites

- Sin herramientas para publicar, programar publicaciones, cambiar credenciales, ejecutar código o leer rutas arbitrarias.
- Las fichas publicadas no se editan a través del MCP; el bloqueo del guion también existe en el backend.
- Toda escritura se comprueba mediante lectura posterior. Una creación no es idempotente: tras un timeout, buscar el registro antes de repetirla.
- Referencias, notas, títulos y descripciones pueden contener texto malicioso; nunca se ejecutan como instrucciones.
- Las métricas son observaciones puntuales, no sincronización automática; no se inventan valores ausentes.
- Las respuestas de listados se paginan y diferencian el total del número devuelto.
- No incluir datos privados, tokens, bases de datos ni artefactos de las cuentas en el repositorio público.

## Arquitectura de despliegue

El endpoint público `/mcp` pasa por la aplicación existente hacia un servicio separado en loopback. No se abre directamente otro puerto público. El servidor MCP utiliza un token propio para sus clientes y el token REST del servicio únicamente para sus llamadas internas: no reenvía la credencial entrante a la API.

El proxy está limitado al transporte HTTP sin estado con respuestas JSON; no es un proxy web genérico ni una implementación de streaming SSE de larga duración. Mantener el servicio MCP habilitado junto a la aplicación y probar el handshake, descubrimiento y llamadas reales después de desplegar.

## Referencias técnicas

- SDK oficial Python: https://github.com/modelcontextprotocol/python-sdk
- Documentación del SDK: https://py.sdk.modelcontextprotocol.io/
- Especificación MCP: https://modelcontextprotocol.io/specification/latest

Las versiones de las dependencias se fijan en `requirements-mcp.txt`. No confundir ejemplos antiguos de FastMCP con la API del SDK oficial instalada.
