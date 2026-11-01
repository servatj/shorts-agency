# Analítica de observaciones

La pestaña **Analítica** es una vista de los registros existentes; no consulta ni sincroniza plataformas. **Actualizar registros** vuelve a leer el endpoint de métricas. No se cambia el contrato de la API, el esquema ni el contenido almacenado en `notes`.

## Presentación y datos

- Cuatro indicadores: visualizaciones, Me gusta, comentarios y compartidos. Cuatro columnas en escritorio, dos por dos en móvil.
- Todos los indicadores proceden de los campos numéricos tipados de una única observación: la más reciente según `observed_at`. Un valor desconocido muestra `—` y «Sin dato»; un cero explícito muestra `0`. Nunca se rellenan huecos con observaciones anteriores ni se calculan interacciones totales o crecimientos inventados.
- Orden descendente por instante observado; los identificadores se usan únicamente para resolver empates de forma determinista (mayor identificador primero, comparación numérica). Fechas no válidas quedan detrás de las válidas y no participan en la gráfica. El historial conserva todas las observaciones, incluso los duplicados.
- Retención y duración media se muestran si están disponibles; las ausencias son explícitas. El historial también conserva esos valores por observación.
- La fecha visible es la fecha observada, localizada al dispositivo, no la fecha de importación. El contexto usa la cuenta, canal y miniatura reales del registro. La vista previa grande se oculta solo en Analítica y vuelve al salir. No se activa ningún reproductor por entrar en esta pestaña.

## Procedencia y seguridad

El prefijo conocido `Observación pública puntual; no sincronización. Fuente: …` se interpreta únicamente como procedencia. Se muestra «Consulta pública», fecha observada y un enlace «Ver fuente» cuando la URL pasa la validación HTTPS estricta, sin credenciales, controles, espacios ni barras inversas. Los demás orígenes se presentan como «Manual» o «Registro del agente».

No se interpreta el JSON de las notas como valores de los indicadores. No se inserta en el DOM el bloque importado, sus identificadores ni las URL como prosa. Notas técnicas o JSON desconocido/malformado se omiten de la presentación, sin modificar lo almacenado. Las notas humanas sencillas quedan en un detalle opcional y se asignan mediante `textContent`, nunca HTML. Todos los enlaces externos llevan `noopener noreferrer`.

## Evolución

El selector permite visualizar cualquiera de los cuatro indicadores. Se requiere un mínimo de dos instantes válidos distintos con valores numéricos de la métrica seleccionada. Un solo punto muestra «Una observación disponible» y ningún punto muestra una explicación de datos insuficientes. Una única captura mantiene el mensaje de observación disponible aunque esa métrica no se conozca.

La gráfica SVG local, sin dependencias, usa valores e instantes reales. Las bajadas de contadores y los valores constantes son válidos. Los registros de un mismo instante se representan una sola vez usando el mismo desempate que los indicadores. Un valor desconocido interrumpe la línea; nunca se transforma en cero. El SVG tiene título, descripción y un detalle legible con los valores y fechas, incluidos los huecos. No hay porcentaje de crecimiento ni interpolación sobre datos ausentes.

## Edición y estados

«Añadir observación» abre el formulario existente: los campos numéricos empiezan vacíos, se validan y se guardan como `null` si no se rellenan. El guardado conserva la comprobación mediante lectura posterior. Los controles de navegación y pérdida de cambios siguen activos; el guion publicado permanece bloqueado.

Al iniciar una carga se vacían indicadores, gráfica e historial. Los errores no dejan datos de la carga anterior; el identificador de petición y el registro actual impiden que una respuesta atrasada contamine otra pieza. Un borrador sin identificador muestra «Guarda primero» sin controles de métricas utilizables.

## Pruebas reproducibles

```sh
RUN_BROWSER_TESTS=1 python -m unittest discover -s tests -v
node --check static/app.js
node --check tests/analytics_browser.cjs
git diff --check
```

Opcionalmente, definir `PLAYWRIGHT_MODULE` y `PLAYWRIGHT_CHROMIUM_EXECUTABLE` para usar una instalación local existente. `ANALYTICS_SCREENSHOTS` puede apuntar a un directorio temporal fuera del repositorio para capturas de 390 y 1536 píxeles.

`tests/test_analytics_ui.py` arranca el servidor HTTP y SQLite aislados con credenciales sintéticas y ejecuta `tests/analytics_browser.cjs`. La creación de vídeos, importación de observaciones, validación y guardado/lectura posterior usan la API real. Solo las respuestas imposibles/malformadas, errores y carreras se inyectan de forma controlada. Se bloquea todo tráfico HTTPS externo; no se descargan vídeos ni se contacta con plataformas.

Evidencia TDD: primero falló la prueba de privacidad porque el historial mostraba `Datos originales` y el JSON; tras la primera implementación pasó. La prueba de evolución falló por ausencia de SVG y pasó con la implementación. La matriz de URL detectó que `https://@…` se normalizaba como enlace válido; se reutilizó la validación estricta y pasó. Una prueba de posición móvil detectó exceso de cabecera antes de los indicadores; se compactó únicamente la vista Analítica. La suite completa detectó que ocultar todos los controles de guardado rompía la validación desde pestañas ocultas; se conservó el guardado de borradores y volvió a pasar.

Verificación final: 57 pruebas de unittest, sin omisiones, incluidas las pruebas Node/Playwright y la prueba Python/Playwright existente. Comprobación de sintaxis Node y `git diff --check` correctas.
