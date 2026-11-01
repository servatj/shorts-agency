# Supabase Free y futuro despliegue en Vercel

Estado: propuesta de migración, NO implementación. La versión publicada sigue usando SQLite y un servidor Python de larga duración. No contiene un proyecto Supabase, esquema PostgreSQL aplicado, despliegue Vercel ni sincronización de archivos. La aplicación existente puede seguir funcionando sin cambios.

## Alcance y coste

Consulta de documentación oficial: 2026-11-01. Revisar las condiciones de nuevo antes de contratar o migrar.

Supabase Free anuncia 500 MB de base de datos, 1 GB de almacenamiento de archivos, 5 GB de salida de datos y otros 5 GB de salida en caché, 50.000 usuarios activos al mes, hasta dos proyectos activos y pausa tras una semana de inactividad. Son límites de partida, no una garantía de capacidad para vídeo ni de disponibilidad de producción. No activar planes de pago ni complementos sin autorización.

Fuente: https://supabase.com/pricing

Vercel Hobby está restringido a uso personal no comercial. No asumir que una aplicación para una agencia comercial cumple esas condiciones. Se puede mantener el alojamiento actual mientras se prueba Supabase, sin contratar Vercel todavía.

Fuente: https://vercel.com/docs/plans/hobby

## Arquitectura propuesta

- Supabase PostgreSQL: cuentas propias, guiones, piezas, observaciones de métricas y referencias externas, conservadas en entidades distintas.
- Supabase Auth: identidad del propietario; no trasladar la contraseña del sistema operativo ni reutilizarla como contraseña de base de datos.
- Acceso a datos: RLS para las tablas expuestas, con políticas que exijan usuario autenticado y propiedad explícita. Ninguna lectura pública de guiones o inventarios por publicar el código en GitHub.
- Agentes: API servidor autenticada con credenciales propias y limitadas; nunca entregar una clave privilegiada de Supabase al navegador ni guardarla en Git.
- Vídeos originales: conservarlos en almacenamiento privado externo o en el servidor actual. Usar Supabase Storage inicialmente para miniaturas pequeñas si conviene; 1 GB no es un archivo de vídeo de producción. El acceso desde el navegador requerirá un endpoint autenticado HTTPS o URLs firmadas, no SFTP.
- Frontend/API futura: adaptar los handlers a un runtime de despliegue elegido. No intentar persistir SQLite o sesiones locales en funciones efímeras. Trabajos largos de renderizado y agentes permanecen fuera del ciclo HTTP.

Fuente sobre RLS: https://supabase.com/docs/guides/database/postgres/row-level-security

## Orden de trabajo y pruebas de aceptación

1. Confirmar la organización y región de Supabase con el propietario, entrar mediante un flujo seguro y comprobar que existe capacidad en el plan Free. Crear un proyecto de pruebas, no sustituir la aplicación existente.
2. Definir migraciones PostgreSQL versionadas. Preservar IDs de cuentas, métricas desconocidas como NULL, fuente y fecha de observación. No interpretar las capturas como consultas en directo.
3. Añadir pruebas de RLS: anónimo rechazado, propietario autorizado, otro usuario denegado; archivos privados; claves privilegiadas ausentes del bundle.
4. Implementar un adaptador de persistencia y probar CRUD, búsqueda completa de guiones, referencias separadas, sesiones, CSRF/origin según el modelo de autenticación y contratos API de agentes.
5. Copiar una muestra sintética y verificarla. La importación de datos personales reales se realizará por una vía privada tras confirmar destino, con copia SQLite intacta y plan de reversión.
6. Verificar recuentos e IDs de toda la importación, ausencia de duplicados, textos completos y metadatos; no copiar contraseñas locales ni sesiones antiguas.
7. Probar login y reproducción real en staging. Elegir alojamiento y plan compatible con el uso comercial antes de configurar un dominio o hacer el cambio.
8. Configurar copias de seguridad fuera del proveedor, avisos de cuota y procedimiento ante pausas. No usar pings para eludir pausas del plan gratuito.

No se incluyen botones ficticios de despliegue ni un vercel.json que aparente compatibilidad. El cambio de diseño visual es independiente y requiere elegir primero una propuesta.
