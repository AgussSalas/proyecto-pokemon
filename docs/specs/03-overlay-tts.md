# Iteración 3 — Overlay visual y texto a voz

## Contexto

Hasta la Iteración 2, la salida es consola (y la voz como entrada). Esta iteración agrega
dos canales de salida nuevos sin tocar `WeaknessService`: una ventana transparente superpuesta
al juego (`OverlayNotifier`, PyQt6) y voz hablada (`TtsNotifier`). `CompositeNotifier` los
combina con `ConsoleNotifier` para que las tres salidas convivan.

**Nota de revisión (2026-10-11):** la primera versión de este documento tenía esta sección
marcada como "no verificada" porque las búsquedas se habían interrumpido. El usuario trajo
dos fuentes puntuales (la documentación de `pyttsx3` y el tutorial de PyQt6 de
pythonguis.com) y con eso se confirmaron los puntos marcados abajo -- quedan citados en la
sección "Fuentes" al final del documento. Lo que sigue sin confirmar queda marcado
explícitamente igual que antes, sin inflar la confianza donde no la hay.

## Decisiones de diseño

### 1. Riesgo más importante de toda la iteración: overlays y fullscreen exclusivo

Esto no está en el prompt original y es la razón por la que esta iteración podría fallar
*en la práctica* aunque el código esté perfecto: en Windows, una ventana superpuesta
(overlay) **no siempre se renderiza arriba de un juego corriendo en fullscreen exclusivo**
-- es la misma razón por la que a veces el overlay de Steam o Discord no aparece en ciertos
juegos. Suele funcionar bien en modo ventana o "fullscreen sin bordes" (borderless
windowed), que es justamente el modo recomendado para emuladores en general.

**Decisión:** documentar esto como requisito de uso (correr el emulador en modo ventana o
fullscreen sin bordes, no fullscreen exclusivo) en vez de intentar resolverlo por código --
no hay garantía de que se pueda resolver puramente desde PyQt6, y es información que el
usuario necesita de todas formas para configurar su emulador. **A confirmar en la
implementación**, probando contra el emulador real que se use.

### 2. Comportamiento visual de la ventana -- pregunta abierta

Necesito que confirmes antes de implementar:
- **Posición**: ¿fija en una esquina (como un "toast" de notificación), o en el centro?
- **Duración**: ¿se queda fija hasta la próxima consulta, o se auto-oculta sola después de
  N segundos?
- **Click-through**: ¿la ventana debe dejar pasar los clics del mouse hacia el juego de
  abajo (para no interferir con el control del juego), o no importa porque nunca se hace
  click ahí?

Mi supuesto de trabajo (a confirmar, no asumido como definitivo): esquina superior derecha,
se actualiza con cada consulta nueva y se mantiene visible hasta la siguiente, click-through
activado.

**Flags confirmadas** (código real verificado en dos tutoriales de pythonguis.com, no
inventadas -- ver "Fuentes"):

```python
self.setWindowFlags(
    Qt.WindowType.FramelessWindowHint      # sin bordes
    | Qt.WindowType.WindowStaysOnTopHint   # siempre encima
)
self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # fondo transparente
```

**Click-through (`Qt.WindowType.WindowTransparentForInput`) -- confirmada, con una trampa
real documentada:** no aparece en ningún tutorial oficial de pythonguis.com (ninguno de los
dos construye una ventana click-through), pero sí en reportes de usuarios en foros de Qt.
Un hallazgo concreto vale la pena anotar antes de implementar: **aplicar esta flag sobre una
ventana que ya está visible la oculta**, y hay que volver a llamar `show()` -- lo que
produce un parpadeo/glitch visible. La forma de evitarlo es setear la flag **antes** del
primer `show()`, nunca después:

```python
overlay.setWindowFlags(
    Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowTransparentForInput
)
overlay.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
overlay.show()  # recién acá, no antes
```

El comportamiento de esta flag puntual también depende del sistema operativo/gestor de
ventanas según esos mismos reportes -- en nuestro caso es sólo Windows, pero conviene
probarlo temprano (Paso 0) y no asumir que se comporta igual que `FramelessWindowHint`/
`WindowStaysOnTopHint`, que sí están confirmadas con código real funcionando.

### 3. TTS: pyttsx3 vs. edge-tts -- pregunta abierta, el prompt original la dejó condicional

El prompt original dice textualmente: *"`pyttsx3` para TTS local (o `edge-tts` si se
prioriza calidad de voz sobre funcionamiento offline)"* -- es decir, ya venía marcada como
una decisión a tomar, no tomada.

| | `pyttsx3` | `edge-tts` |
|---|---|---|
| Red en runtime | No -- motor SAPI5 de Windows, una API del sistema operativo. La documentación de `pyttsx3` no lo afirma explícitamente, pero SAPI5 es una API local de Windows desde XP; no hay razón técnica para que llame a red | Sí -- llama a un servicio de Microsoft por cada frase |
| Calidad de voz en español | **Confirmado el mecanismo, no el resultado en tu máquina.** `engine.getProperty('voices')` devuelve objetos con `.id` y `.languages`; se filtra por `.languages` buscando español y se activa con `engine.setProperty('voice', voice.id)`. Si Windows no tiene un paquete de voz en español instalado, la lista puede no traer ninguna -- **a confirmar corriendo ese filtro en tu máquina**, es el Paso 0 de esta decisión | Voces neuronales de Edge, notablemente mejores, sin depender de qué tenga instalado Windows |
| Comportamiento al hablar | `engine.say(texto)` sólo encola; `engine.runAndWait()` recién ahí procesa la cola y **bloquea** hasta terminar de hablar todo lo encolado. Importa para el diseño: si se llama desde el hilo principal, congela el loop del REPL mientras habla -- probablemente quererlo en un hilo aparte, no en el consumidor único de la Decisión 4 | No confirmado en esta sesión |
| Control de voz | `setProperty('rate', n)` (enteros, default 200 palabras/min) y `setProperty('volume', x)` (float 0.0-1.0, default 1.0) | No confirmado en esta sesión |
| Windows soportado | La documentación lista XP, Vista, 8, 8.1 y 10 probados -- **no menciona Windows 11 explícitamente**. SAPI5 no cambió entre esas versiones y 11, así que debería funcionar igual, pero es una inferencia, no algo que la documentación confirme | -- |
| Consistencia con el resto del proyecto | Alta -- el diseño original insiste en que el runtime nunca llama a servicios externos | Introduce la primera llamada de red en tiempo real de todo el proyecto |

Dado que el port `Notifier` ya los trata como adapters intercambiables, el costo de dejar
esto abierto es cero -- `TtsNotifier` (pyttsx3) y `EdgeTtsNotifier` (edge-tts) son dos
clases que satisfacen el mismo contrato. Mi recomendación es arrancar con `pyttsx3` por
coherencia con el resto del proyecto (cero dependencia de red) y sólo pasar a `edge-tts` si
la calidad de voz en la práctica resulta insuficiente -- pero el primer paso concreto, antes
de decidir nada, es correr `engine.getProperty('voices')` en tu Windows y ver qué aparece en
español. Si no hay nada, la decisión se simplifica sola. Igual quiero tu confirmación antes
de implementar, dado que el prompt original lo dejó explícitamente como tu decisión.

### 4. El mismo problema de threading que en la Iteración 2, versión Qt

El hotkey de voz (Iteración 2) dispara callbacks en un hilo de `keyboard`, fuera del hilo
donde corre el event loop de Qt (`QApplication.exec()`). Tocar una ventana PyQt6 desde un
hilo que no es el principal de Qt **no está soportado** y causa comportamiento indefinido o
crashes intermitentes -- no es un detalle menor, es una de las causas más comunes de bugs
"funciona la mayoría de las veces" en apps Qt con hilos.

**Decisión, corregida tras verificar el patrón real en pythonguis.com:** mismo espíritu que
la Iteración 2 (nunca tocar la ventana desde el hilo del hotkey), pero el mecanismo es un
poco distinto de lo que había escrito originalmente. No hace falta forzar
`Qt.ConnectionType.QueuedConnection` a mano: Qt usa por default `AutoConnection`, que
**detecta solo** cuándo el emisor de una señal está corriendo en un hilo distinto al del
objeto receptor, y en ese caso encola la llamada automáticamente -- sin que el código tenga
que pedirlo explícitamente. El patrón confirmado (con código real de las FAQ de
pythonguis.com, ver "Fuentes") es:

```python
class OverlayWorker(QObject):
    weakness_ready = pyqtSignal(str)  # la señal vive en un QObject

# en el hilo del hotkey (keyboard), o en el consumidor único de la Iteración 2:
overlay_worker.weakness_ready.emit(texto)

# conectado una sola vez, en el hilo principal, al construir la ventana:
overlay_worker.weakness_ready.connect(self.label.setText)
```

El punto importante: el hilo que hace `.emit(...)` puede ser *cualquier* hilo -- incluido
uno que ni siquiera es un `QThread` de Qt, como el hilo propio de la librería `keyboard`.
Qt sabe en qué hilo "vive" el objeto receptor (`self.label`, creado en el hilo principal) y
entrega la llamada ahí de forma segura. Esto simplifica el diseño: no hace falta que
`OverlayNotifier` pase por la cola de la Decisión 3 de la Iteración 2 -- puede emitir su
señal directo desde donde se lo llame, y Qt se encarga del resto. La cola de la Iteración 2
sigue haciendo falta igual para el acceso a SQLite (eso no tiene un mecanismo equivalente al
de Qt), pero para la ventana específicamente, la señal ya resuelve el problema sola.

### 5. `CompositeNotifier`

Ya está bocetado en la explicación de la Iteración 1 (carpeta `adapters/`): una lista de
notifiers reales, y cada método (`notify_weakness_report`, `notify_ability_info`) los
recorre y llama a todos. Sin novedad de diseño acá -- es la pieza más simple de esta
iteración.

## Plan de ejecución

**Paso 0 -- Confirmar lo que todavía falta.** Los flags de Qt (Decisión 2) y el mecanismo de
threading (Decisión 4) ya están verificados con código real. Queda pendiente: (a) correr
`engine.getProperty('voices')` de `pyttsx3` en esta máquina Windows y ver si hay una voz en
español disponible -- decide la Decisión 3 casi sola; (b) confirmar con el usuario las
preguntas de posición/duración/click-through de la Decisión 2; (c) probar que una ventana
PyQt6 básica con `WindowTransparentForInput` se vea y deje pasar los clics arriba del
emulador real que se use (Decisión 1), seteando la flag antes del primer `show()` para
evitar el parpadeo documentado.

**Paso 1 -- `OverlayNotifier`.** Ventana PyQt6 mínima, actualiza su texto vía señal con
conexión encolada.

**Paso 2 -- `TtsNotifier`** (o `EdgeTtsNotifier`, según la Decisión 3). Convierte
`WeaknessReport`/`AbilityCaveat` a una frase hablable -- notar que el formato compacto de
consola ("×4 Roca") no se lee bien en voz alta; hace falta una frase tipo "Charizard es
débil a Roca por cuatro, y a Agua y Eléctrico por dos".

**Paso 3 -- `CompositeNotifier`.**

**Paso 4 -- `main.py`.** Construye `CompositeNotifier([ConsoleNotifier(), OverlayNotifier(...), TtsNotifier(...)])`
en vez de un `ConsoleNotifier()` solo. Nada más cambia en el resto del composition root.

**Paso 5 -- Tests.** `CompositeNotifier` se testea con fakes de `Notifier` verificando que
llama a todos. `OverlayNotifier`/`TtsNotifier` reales son difíciles de testear
automáticamente (abren una ventana / hablan) -- se verifican a mano, no en `pytest`.

## Verificación

| Caso | Criterio |
|---|---|
| Emulador en modo ventana/borderless | El overlay se ve arriba del juego |
| Emulador en fullscreen exclusivo | Documentado como no soportado (Decisión 1) -- no se trata como bug si falla acá |
| Consulta por voz con el overlay abierto | Se actualiza sin crashear (verifica la Decisión 4) |
| TTS habla una debilidad | La frase es entendible, no lee "×4 Roca" literal |
| Las tres salidas activas a la vez | Consola, overlay y voz muestran lo mismo para la misma consulta |

## Qué queda explícitamente afuera

OCR/reconocimiento de pantalla (Iteración 4).

## Fuentes

Verificado contra estas páginas en esta sesión (no de memoria):

- [pyttsx3 docs — Engine](https://pyttsx3.readthedocs.io/en/latest/engine.html) — voces,
  `say()`/`runAndWait()`, `rate`/`volume`.
- [pyttsx3 docs — Platform support](https://pyttsx3.readthedocs.io/en/latest/support.html)
  — SAPI5 en Windows, versiones listadas.
- [PythonGUIs — Custom Title Bar for PyQt6](https://www.pythonguis.com/tutorials/custom-title-bar-pyqt6/)
  — `FramelessWindowHint`, `WA_TranslucentBackground`.
- [PythonGUIs — Sticky Notes (PySide6)](https://www.pythonguis.com/examples/pyside6-desktop-sticky-notes/)
  — `WindowStaysOnTopHint` combinado con `FramelessWindowHint` vía OR bitwise.
- [PythonGUIs — PyQt6 Thread Communication Between Windows](https://www.pythonguis.com/faq/actions-in-one-thread-changing-data-in-another/)
  — patrón de señal cross-thread que resuelve la Decisión 4.
- Foros de Qt (`qtcentre.org`, `forum.qt.io`) sobre `WindowTransparentForInput` -- el
  parpadeo al aplicarlo sobre una ventana ya visible es un reporte de usuario, no
  documentación oficial; tratarlo como advertencia a verificar, no como hecho garantizado.
