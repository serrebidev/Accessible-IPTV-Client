<!--
Guía del usuario de Accessible IPTV Client, en español. La referencia en
inglés está en docs/help/en.md. Nota para traductores: conservar los
identificadores {#topic ID} tal cual; traducir solo el texto del encabezado.
Una sección aún sin traducir puede omitirse; F1 abrirá entonces la sección
en inglés.
-->

# Guía del usuario de Accessible IPTV Client {#user-guide}

Accessible IPTV Client reproduce televisión en vivo, radio y video bajo demanda de proveedores IPTV. Está construido para el teclado y para lectores de pantalla como NVDA, JAWS, Narrador y Orca, y soporta listas de reproducción y guías de programación muy grandes.

Esta guía explica cada parte del programa. Pulse F1 en cualquier lugar del programa para abrirla en la sección sobre lo que esté usando en ese momento.

## Usar esta guía {#using-help}

La ventana de la guía tiene cuatro partes, en orden de Tabulación:

- Temas: la lista de secciones. Moverse por ella con las flechas mueve el texto de la guía a esa sección. Pulse Intro para entrar directamente en el texto.
- Texto de la guía: toda la guía como un documento de solo lectura. Léalo con las flechas o con el comando de lectura continua de su lector de pantalla; seleccionar y copiar texto funciona como en cualquier documento.
- Buscar: escriba una palabra y pulse Intro para saltar al siguiente lugar donde aparece.
- Cerrar.

Teclas en la ventana de la guía:

- Ctrl+F: ir al campo Buscar.
- F3: buscar la siguiente coincidencia. Shift+F3: buscar la anterior.
- F1: volver a esta sección.
- Escape: cerrar la guía y volver a donde estaba.

F1 es contextual. Pulsado sobre un elemento de menú, en un diálogo, en el reproductor integrado o sobre un control de la ventana principal, abre la guía en la sección sobre ese elemento. Donde aún no hay sección escrita, la guía se abre al principio. Ayuda > Guía del usuario siempre la abre al principio.

La guía es parte del programa, así que funciona sin conexión a Internet. Se muestra en el idioma de la interfaz del programa cuando existe traducción, y en inglés en caso contrario.

## Primeros pasos {#getting-started}

1. Abra Archivo > Administrador de listas de reproducción (Ctrl+M) y añada su proveedor: un archivo o dirección de lista M3U, una cuenta de Xtream Codes o una cuenta de Stalker Portal. Elija Aceptar. Los canales se cargan en segundo plano.
2. Si su proveedor le da una dirección de guía de programación (EPG), añádala en Archivo > Administrador de EPG (Ctrl+E). Las cuentas de Xtream Codes pueden añadirla por usted.
3. Importe la guía con Archivo > Importar EPG a la base de datos (Ctrl+I). Se ejecuta en segundo plano y le avisa cuando termina.
4. Elija una categoría, elija un canal y pulse Intro para reproducirlo.

Sus listas de reproducción, fuentes de guía y ajustes se conservan entre sesiones, así que esto solo hay que hacerlo una vez.

## La ventana principal {#main-window}

La ventana principal es donde navega y reproduce canales. Tab recorre sus controles en este orden, y Shift+Tab va hacia atrás:

1. Vista de lista de reproducción: qué lista navegar.
2. Categorías: los grupos de canales.
3. Buscar: filtra la lista de canales.
4. Canales: los canales de la categoría elegida, o los resultados de búsqueda.
5. Descripción del episodio: qué se emite ahora en el canal resaltado.
6. URL del flujo: la dirección del canal resaltado, visible solo cuando Opciones > Mostrar la URL del flujo está activada.

Después del último control, Tab vuelve al primero.

En Linux, los menús que describe esta guía están bajo el botón Menú en la parte superior de la ventana.

### Vista de lista de reproducción {#playlist-view}

Cuando tiene más de una lista de reproducción, la lista Vista de lista de reproducción elige qué muestran las categorías y los canales: todas las listas o una sola. Su elección se recuerda.

### Categorías {#categories}

La lista de categorías contiene los grupos de canales de sus listas. Sus primeras filas son Todos los canales y, una vez añadidos algunos, Favoritos. Cada fila indica cuántos canales contiene.

- Las flechas arriba y abajo recorren las categorías sin cambiar la lista de canales, para que pueda escucharlas primero.
- Intro abre la categoría resaltada y pasa a la lista de canales.
- Tab abre la categoría resaltada y pasa al campo Buscar.
- Las flechas izquierda y derecha contraen y expanden una categoría con subgrupos.

### Búsqueda {#search}

Escriba en el campo Buscar para filtrar la lista de canales, y pulse Intro o Tab para aplicar el filtro y continuar. Buscar en Todos los canales también consulta la guía de programación, así que una búsqueda por título de programa puede listar los canales que lo emiten. Vacíe el campo y pulse Intro para volver a ver toda la categoría.

### La lista de canales {#channel-list}

La lista de canales muestra los canales de la categoría o búsqueda elegida.

- Intro reproduce el canal resaltado.
- La tecla de aplicaciones, Shift+F10 o un clic derecho abre el menú del canal: Reproducir, Añadir a favoritos o Quitar de favoritos, Grabar o Detener grabación, Programar grabación, Ver EPG…, y Repetición en los canales que tienen archivo.
- Ctrl+D añade el canal a favoritos o lo quita. En la categoría Favoritos, Supr lo elimina.
- Ctrl+Shift+R inicia la grabación del canal; pulsado de nuevo, la detiene.

Los canales favoritos se marcan con "(Favorito)", y cada fila también nombra el programa en emisión cuando la guía lo tiene. Cuando una búsqueda también encontró programas, sus filas nombran el programa y el canal que lo emite.

### Descripción del episodio y URL del flujo {#episode-description}

Tab desde la lista de canales llega a la Descripción del episodio: el programa en emisión en el canal resaltado, con sus horarios y descripción, y lo que viene después. Shift+Tab vuelve directamente a la lista de canales. El texto sigue al canal resaltado.

Cuando Opciones > Mostrar la URL del flujo está activada, el campo URL del flujo aparece un Tab después. Muestra la dirección del canal, útil para reportar problemas. La mayoría la deja desactivada.

## Favoritos {#favorites}

Los favoritos mantienen en un solo lugar los canales que más ve. Pulse Ctrl+D sobre un canal, use su menú, o Ver > Añadir a favoritos. Los favoritos aparecen en la categoría Favoritos cerca del inicio de la lista de categorías, y Ver > Ir a favoritos le lleva allí.

Para quitar un favorito, pulse Ctrl+D sobre él de nuevo, o pulse Supr en la categoría Favoritos.

Los favoritos se guardan por proveedor y canal, no por dirección de flujo, así que sobreviven a una actualización de la lista. Nada de su cuenta se guarda con ellos.

## Video bajo demanda {#video-on-demand}

Ver > Video bajo demanda (películas && series) cambia la lista de categorías de canales en vivo a las películas y series de su proveedor. Las categorías se llaman Movies o Series seguidas de la categoría del proveedor. Elegir una serie lista sus episodios en orden de temporada y episodio. Pulse Intro para reproducir una película o un episodio.

Ver > TV en vivo && Repetición vuelve a los canales en vivo. El campo de búsqueda se vacía al cambiar.

El video bajo demanda funciona mejor con cuentas de Xtream Codes, que describen bien su catálogo. En listas M3U simples el programa reconoce películas y series por sus nombres de grupo y numeración de episodios.

## Administrador de listas de reproducción {#playlist-manager}

Archivo > Administrador de listas de reproducción (Ctrl+M) enumera sus fuentes de listas. Se abre con el foco en la lista.

- Agregar archivo: una lista M3U o M3U8 en su equipo.
- Agregar URL: la dirección de internet de una lista M3U.
- Agregar Xtream Codes: una cuenta de Xtream Codes.
- Agregar Stalker Portal: una cuenta de portal Stalker (MAG).

Sobre una fuente de la lista, la tecla de aplicaciones o Shift+F10 abre su menú: Copiar URL, Renombrar (F2) y Eliminar (Supr). Un nombre que dé a una fuente es solo una etiqueta; no cambia la fuente.

Elija Aceptar para conservar sus cambios, o Cancelar para descartarlos. Los canales se recargan tras Aceptar.

### Cuentas de Xtream Codes {#xtream-codes}

Una cuenta de Xtream Codes necesita la dirección del servidor, su nombre de usuario y su contraseña, que le da su proveedor. El nombre es su propia etiqueta para la cuenta. Deje marcada "Agregar automáticamente la URL de XMLTV" para añadir la guía del proveedor al Administrador de EPG al mismo tiempo.

Las cuentas de Xtream Codes también le dan video bajo demanda, repetición donde el proveedor la ofrece, y el estado de la cuenta en Archivo > Información de la cuenta.

### Cuentas de Stalker Portal {#stalker-portal}

Una cuenta de Stalker Portal necesita la dirección del portal y la dirección MAC que su proveedor registró para usted. Algunos portales también piden usuario y contraseña. "Aleatorizar MAC" inventa una nueva dirección MAC, útil solo cuando el proveedor le pide elegir una. "Intentar agregar el XMLTV del proveedor" añade la guía del portal cuando tiene una.

## Guía de programación (EPG) {#epg}

La guía de programación, o EPG, le dice qué se emite en cada canal ahora y después. Proviene de archivos XMLTV que publica su proveedor u otra fuente. El programa los importa a una base de datos local y los usa para la descripción del episodio, Qué hay ahora, Ver EPG…, listas de repetición y búsquedas.

### Administrador de EPG {#epg-manager}

Archivo > Administrador de EPG (Ctrl+E) enumera sus fuentes de guía.

- Agregar archivo: un archivo XMLTV en su equipo (.xml o .xml.gz).
- Agregar URL: la dirección de internet de una guía XMLTV.

La tecla de aplicaciones o Shift+F10 sobre una fuente abre su menú: Copiar URL, Renombrar (F2) y Eliminar (Supr). Elija Aceptar para conservar sus cambios.

### Importar la guía {#import-epg}

Archivo > Importar EPG a la base de datos (Ctrl+I) descarga cada fuente de guía y la carga en la base de datos. Se ejecuta en segundo plano, así que puede seguir viendo y navegando, y un mensaje avisa cuando termina. Las guías grandes pueden tardar varios minutos.

La guía también se refresca automáticamente de vez en cuando, en silencio. Los canales se emparejan con la guía por su identificador y sus nombres, incluidas las variantes habituales de país y calidad en los nombres de canal.

Si una guía importada no aparece para un canal, compruebe que alguna de sus fuentes lo cubra, e importe de nuevo. La importación escribe un registro detallado; vea Solución de problemas.

### Qué hay ahora {#whats-on-now}

Archivo > Qué hay ahora (Ctrl+W) enumera todo programa en emisión ahora en todos los canales, como "programa - canal".

- Escribir letras salta al primer programa que empieza con ellas.
- Tab pasa al campo Filtro; escribir allí acota la lista a los programas o canales coincidentes.
- Intro o el botón Reproducir reproduce el canal.
- Programar grabación, o el menú del programa, programa su grabación.
- Escape cierra la ventana.

### Guía del canal (Ver EPG) {#channel-epg}

Ver EPG…, en el menú de un canal, enumera los programas de ese canal desde el que está en emisión hasta donde alcance la guía. El programa en emisión va primero.

- Tab alterna entre la lista y la descripción del programa resaltado.
- La tecla de aplicaciones o Shift+F10 sobre un programa ofrece Programar grabación.
- Escape cierra la ventana.

## Repetición {#catch-up}

Los canales que guardan un archivo permiten ver programas ya emitidos. Estos canales tienen Repetición en su menú en la lista de canales. Abre la ventana de repetición del canal, que lista sus programas pasados con fecha y hora.

- Las flechas arriba y abajo recorren los programas.
- Intro reproduce el programa resaltado.
- La tecla de aplicaciones o Shift+F10 abre su menú: Abrir, para reproducirlo, y Descargar, para guardarlo como archivo.
- Tab pasa a la descripción del programa y vuelve.
- Escape cierra la ventana.

Al cerrar el reproductor integrado tras ver un programa de repetición, vuelve a la lista de repetición en el mismo programa.

Cuánto hacia atrás pueda ir depende de su proveedor, normalmente unos días.

### Descargas de repetición {#catch-up-downloads}

Descargar guarda un programa de repetición en su carpeta de descargas (vea Grabaciones), nombrado por el canal y la emisión del programa. Cada descarga tiene su propia ventana con progreso, tiempo transcurrido, tiempo restante y tamaño hasta ahora, todo en un campo de solo lectura.

- Escape, o cerrar la ventana, la oculta; la descarga continúa.
- Ver > Mostrar descargas (Ctrl+Shift+D) trae de vuelta las ventanas de descarga.
- Cancelar detiene la descarga tras pedir confirmación. Una descarga cancelada no se puede reanudar.

Si una descarga falla, la ventana dice por qué y lo reintenta automáticamente unas veces si el problema puede ser temporal. Muchos proveedores permiten un solo flujo a la vez; detenga otra reproducción de la misma cuenta si se rechaza una descarga.

## Reproductor integrado {#built-in-player}

El reproductor integrado reproduce canales dentro del programa. Se abre al reproducir un canal, salvo que Opciones > Mostrar el reproductor al presionar Entrar esté desactivado; entonces la reproducción empieza sin mostrar la ventana.

Sus controles, en orden de Tabulación: Reproducir/Pausar, Detener, Grabar, Transmitir, Pantalla completa, el deslizador de Volumen y Elegir pista de audio.

Teclas en el reproductor:

- Espacio: pulsa el botón con foco, así que en Reproducir/Pausar pausa y reanuda.
- Ctrl+P: reproducir o pausar.
- Ctrl+S: detener.
- Ctrl+R: grabar lo que está viendo, y detener esa grabación.
- Flechas arriba y abajo: volumen en pasos de 2%. Ctrl+Arriba y Ctrl+Abajo: pasos de 5%.
- A: siguiente pista de audio.
- D: elegir el dispositivo de salida de audio.
- Ctrl+C: transmitir a un dispositivo.
- F11: pantalla completa activada o desactivada. Escape la abandona.
- Ctrl+W: ocultar la ventana del reproductor; la reproducción continúa.
- Ctrl+Q: cerrar el reproductor y detener la reproducción.

Los mismos comandos están en el menú Reproducción del reproductor. El reproductor se reconecta solo cuando un flujo en vivo se corta, y mantiene la pista de audio que eligió.

### Pistas de audio {#audio-tracks}

Los canales pueden llevar varias pistas de audio, como otros idiomas o audiodescripción. Pulse A para pasar a la siguiente pista, use Reproducción > Pista de audio, o Tab hasta Elegir pista de audio, que siempre nombra la pista en reproducción.

Una pista que elija se recuerda para ese canal y vuelve la próxima vez. Para elegirlas automáticamente, vea Pista de audio preferida.

### Dispositivo de salida de audio {#audio-output-device}

Reproducción > Dispositivo de salida de audio… (D) elige los altavoces o auriculares que usa el reproductor, por ejemplo para alejar el sonido del TV de su lector de pantalla. Predeterminado del sistema sigue al dispositivo predeterminado de Windows. La elección se recuerda.

### Controlar el reproductor desde la ventana principal {#player-from-main-window}

El menú Reproductor de la ventana principal actúa sobre el reproductor integrado sin cambiar a él:

- Mostrar reproductor integrado: Ctrl+Shift+J.
- Reproducir/Pausar: Ctrl+Shift+P.
- Detener: Ctrl+Shift+S.
- Transmitir / Conectar…: Ctrl+Shift+C.
- Ctrl+Arriba y Ctrl+Abajo cambian el volumen.

## Reproductor multimedia {#media-player}

Opciones > Reproductor multimedia a usar elige qué reproduce sus canales: el Reproductor integrado, o un reproductor externo como VLC, MPC, MPC-BE, MPV, PotPlayer, Kodi o SMPlayer. Reproductor personalizado… permite elegir cualquier otro programa por su archivo.

La grabación, las descargas de repetición y la transmisión funcionan igual con el reproductor que elija. Las funciones de pista de audio y las teclas del reproductor descritas en esta guía pertenecen al reproductor integrado.

## Pista de audio preferida {#preferred-audio-track}

Opciones > Pista de audio preferida hace que el reproductor integrado elija una pista de audio por sí mismo.

- "Preferir una pista de audiodescripción cuando el canal tenga una" elige audiodescripción dondequiera que se ofrezca. Reconoce los nombres que los proveedores usan realmente en varios idiomas, como audio description, AD, Audiodeskription y Hörfilm, y la marca que las emisoras ponen en tales pistas.
- El campo de texto admite nombres de pista o idiomas, los más deseados primero, separados por comas, por ejemplo: audio description, Spanish. Déjelo vacío para conservar la pista con la que un canal comienza.

Una pista que elija a mano en el reproductor se recuerda para ese canal y tiene prioridad sobre estas reglas la próxima vez que lo vea. La última pista elegida en cualquier lugar se usa en los canales para los que nunca eligió una.

Las grabaciones siguen la misma elección. Una grabación de solo audio conserva la pista que habría oído, y una grabación de video conserva todas las pistas marcando esa como predeterminada.

## Grabaciones {#recordings}

El programa puede grabar cualquier canal a un archivo mientras ve otra cosa, o sin reproducir nada.

- Grabaciones > Iniciar grabación (Ctrl+Shift+R) graba el canal resaltado. Pulsado de nuevo, se detiene.
- Grabar en el menú de un canal hace lo mismo, y Grabar en el reproductor integrado (Ctrl+R) graba lo que está viendo.
- Grabaciones > Detener grabación detiene la grabación del canal resaltado, y Detener todas las grabaciones las detiene todas.
- Grabaciones > Abrir carpeta de grabaciones abre la carpeta donde se guardan los archivos.
- Grabaciones > Establecer carpeta de descarga… elige esa carpeta. Las descargas de repetición también van allí.

Grabar lo que ve en el reproductor integrado usa la misma conexión al proveedor, así que funciona incluso con cuentas que permiten un solo flujo a la vez.

Detener una grabación puede tardar un momento mientras el archivo se finaliza. Al cerrar el programa, las grabaciones en curso terminan sus archivos por sí solas.

### Formato de grabación {#recording-formats}

Grabaciones > Formato de grabación elige cómo se guardan las grabaciones:

- Calidad del proveedor (copia, MKV): el flujo exactamente como se emite, con todas las pistas de audio y subtítulos. Conserva todo lo que el proveedor envía.
- Calidad del proveedor (copia, MP4): la misma imagen y sonido en un archivo MP4, que reproducen más dispositivos, sin subtítulos ni teletexto.
- Recodificación x264 (MKV o MP4): un archivo recodificado más pequeño. Usa mucho más tiempo de procesador.
- Solo audio (MP3 V0, FLAC, WAV, AAC M4A u Opus): solo el sonido, útil para radio.

### Grabaciones programadas {#scheduled-recordings}

Para grabar un programa futuro, elija Programar grabación sobre un programa en Ver EPG…, Qué hay ahora o una fila de programa en los resultados de búsqueda. Programar grabación sobre un canal abre su guía para que elija primero el programa.

Grabaciones > Grabaciones programadas… enumera cada grabación programada, en curso y terminada con su hora, título, canal, estado y formato.

- La tecla de aplicaciones o Shift+F10 sobre una grabación abre su menú: Actualizar, Cancelar y Eliminar.
- Eliminar quita la grabación resaltada de la lista; una en curso se detiene primero tras preguntarle.
- Escape cierra la ventana.

Las grabaciones programadas comienzan solas mientras el programa está en ejecución, incluso minimizado a la bandeja del sistema.

### Margen de programación {#schedule-padding}

Los programas rara vez empiezan y terminan exactamente a tiempo. Grabaciones > Margen de programación… fija cuántos minutos antes de un programa comienza una grabación programada, y cuántos minutos después de su fin sigue grabando. Las grabaciones manuales no se ven afectadas.

### Apagado tras las grabaciones {#shutdown-after-recordings}

Grabaciones > Apagar el equipo cuando terminen las grabaciones apaga el equipo cuando toda grabación en curso y programada haya terminado, útil para una grabación de madrugada.

Nunca se activa mientras algo siga grabando o esperando en la agenda. Cuando llega el momento, una ventana cuenta atrás 60 segundos; el foco está en Cancelar apagado, así que Intro o Escape lo detienen, y Apagar ahora no espera. La opción se desactiva sola tras usarse o cancelarse.

## Transmisión {#casting}

Transmitir envía un canal a un televisor o altavoz de su red: dispositivos Chromecast, renderizadores DLNA y UPnP, y dispositivos AirPlay como Apple TV y HomePod.

Archivo > Transmitir a… busca en su red y enumera los dispositivos que encuentra. Elija un dispositivo y Conectar. Algunos dispositivos AirPlay necesitan primero Emparejar…, que pide el código mostrado en el televisor. Una vez conectado, reproducir un canal lo envía al dispositivo. Elegir de nuevo Transmitir a… desconecta.

El botón Transmitir del reproductor integrado, Reproductor > Transmitir / Conectar… (Ctrl+Shift+C) y Ctrl+C en el reproductor hacen lo mismo.

Para transmitir, el equipo y el dispositivo deben estar en la misma red.

## Información de la cuenta {#account-info}

Archivo > Información de la cuenta (Ctrl+Shift+A) muestra el estado de sus cuentas de Xtream Codes y Stalker Portal: si la cuenta está activa, su fecha de caducidad y los días restantes, si es de prueba, y cuántas conexiones permite y tiene abiertas. Las cuentas halladas en direcciones de listas también se enumeran.

Elija una cuenta en la lista; sus detalles aparecen en el campo de solo lectura de abajo. Actualizar pregunta de nuevo al proveedor, y Copiar detalles pone los detalles en el portapapeles. Las contraseñas nunca se muestran.

## Opciones {#options}

El menú Opciones contiene los ajustes del programa. Cada uno se guarda en cuanto lo cambia.

- Reproductor multimedia a usar: vea Reproductor multimedia.
- Pista de audio preferida: vea Pista de audio preferida.
- Idioma: vea Idioma.
- Minimizar a la bandeja del sistema: vea Bandeja del sistema.
- Mostrar el reproductor al presionar Entrar: activado, reproducir un canal muestra la ventana del reproductor integrado. Desactivado, la reproducción empieza y el foco se queda en la lista de canales.
- Mostrar la URL del flujo: añade el campo URL del flujo tras la descripción del episodio en la ventana principal.
- Buscar actualizaciones automáticamente: vea Actualizaciones.

### Idioma {#language}

Opciones > Idioma elige el idioma del programa. Automático sigue al de su Windows o escritorio y usa inglés cuando no hay traducción para él. El cambio se aplica por completo tras reiniciar el programa.

El programa está disponible en inglés, español, árabe, portugués de Brasil, francés, alemán, ruso, turco, italiano, polaco, hindi, chino simplificado, japonés y húngaro. Las correcciones y los nuevos idiomas son bienvenidos; vea Obtener ayuda.

### Bandeja del sistema {#system-tray}

Cuando Opciones > Minimizar a la bandeja del sistema está activado, cerrar o minimizar la ventana principal la oculta en el área de notificación en lugar de salir, así las grabaciones programadas siguen. Active el icono de la bandeja para recuperar la ventana. Su menú también tiene Restaurar, Controles del reproductor, Detener grabación(es) mientras algo graba, y Salir.

Para salir del programa por completo, use Archivo > Salir (Ctrl+Q).

## Actualizaciones {#updates}

En Windows el programa puede actualizarse solo. Ayuda > Buscar actualizaciones… busca una versión nueva ahora, y Opciones > Buscar actualizaciones automáticamente comprueba en segundo plano de vez en cuando.

Cuando hay una actualización, se le dice qué hay de nuevo y se le pregunta si instalarla. La descarga se comprueba antes de instalar nada. El programa se cierra durante la actualización y se reinicia solo al terminar; luego le dice si tuvo éxito. Sus ajustes, favoritos y grabaciones se conservan.

En Linux, instale el paquete nuevo sobre el antiguo.

## Solución de problemas {#troubleshooting}

- Ayuda > Abrir carpeta de registros abre la carpeta con los archivos de registro del programa, incluido el registro de las importaciones de guía y un registro por grabación.
- Ayuda > Copiar registro e información de depuración copia un informe con la versión del programa, su sistema y líneas de registro recientes al portapapeles, listo para pegar en un informe de error. Contiene sus direcciones de flujo, que pueden incluir su inicio de sesión del proveedor; revíselo antes de compartirlo públicamente.

Problemas comunes:

- Un canal no reproduce: muchos proveedores permiten un solo flujo por cuenta a la vez. Detenga otra reproducción, grabación o descarga de la misma cuenta e inténtelo de nuevo.
- Un canal no tiene guía: compruebe que una de sus fuentes EPG lo cubra, e importe la guía de nuevo.
- La reproducción se entrecorta: el reproductor integrado ajusta su búfer por sí mismo. Puede subir internal_player_buffer_seconds e internal_player_max_buffer_seconds en iptvclient.conf para un búfer más paciente.
- La repetición dice que el programa no está disponible: probablemente es más antiguo que el archivo de su proveedor.

## Atajos de teclado {#keyboard-shortcuts}

En cualquier lugar:

- F1: ayuda sobre lo que esté usando.

Ventana principal:

- Ctrl+M: Administrador de listas de reproducción.
- Ctrl+E: Administrador de EPG.
- Ctrl+I: Importar EPG a la base de datos.
- Ctrl+W: Qué hay ahora.
- Ctrl+Shift+A: Información de la cuenta.
- Ctrl+D: añadir el canal seleccionado a favoritos, o quitarlo.
- Supr: quitar el canal seleccionado de favoritos, en la categoría Favoritos.
- Ctrl+Shift+R: iniciar o detener la grabación del canal seleccionado.
- Ctrl+Shift+D: mostrar las ventanas de descarga de repetición.
- Ctrl+Shift+J: mostrar el reproductor integrado.
- Ctrl+Shift+P: reproducir o pausar el reproductor integrado.
- Ctrl+Shift+S: detener el reproductor integrado.
- Ctrl+Shift+C: transmitir o conectar.
- Ctrl+Arriba y Ctrl+Abajo: volumen del reproductor integrado.
- Intro: reproducir el canal seleccionado.
- Tecla de aplicaciones o Shift+F10: el menú del canal.
- Ctrl+Q: salir.

Reproductor integrado:

- Espacio: pulsar el botón con foco, como Pausar.
- Ctrl+P: reproducir o pausar.
- Ctrl+S: detener.
- Ctrl+R: grabar.
- Arriba y Abajo: volumen en pasos de 2%; con Ctrl, pasos de 5%.
- A: siguiente pista de audio.
- D: dispositivo de salida de audio.
- Ctrl+C: transmitir.
- F11: pantalla completa; Escape la abandona.
- Ctrl+W: ocultar el reproductor.
- Ctrl+Q: cerrar el reproductor.

Listas de fuentes en el Administrador de listas de reproducción y el Administrador de EPG:

- F2: renombrar.
- Supr: eliminar.

## Obtener ayuda {#support}

Preguntas, informes de errores y noticias de versiones:

- El grupo de Telegram SerrebiProjects: https://t.me/SerrebiProjects
- Informes de errores y sugerencias en GitHub: https://github.com/serrebidev/Accessible-IPTV-Client/issues

Ayuda > Acerca de… muestra la versión en uso y enlaza ambos. Al reportar un problema, Ayuda > Copiar registro e información de depuración da los detalles necesarios para rastrearlo.
