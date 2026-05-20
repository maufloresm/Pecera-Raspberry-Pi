# 🐠 Pecera Inteligente — Raspberry Pi

Proyecto de IoT para una pecera inteligente usando Raspberry Pi, Firebase y Flask.

El sistema permite controlar distintos dispositivos de la pecera en tiempo real desde Firebase, además de monitorear el estado del agua y transmitir video en vivo desde la cámara conectada a la Raspberry Pi.

---

## Funciones

* 📹 Stream de cámara en vivo desde navegador
* 💡 Control de luces
* 🌊 Control de bomba de oxígeno
* 🧼 Control de filtro de agua
* 🐟 Alimentador automático con servo
* 💧 Sensor de turbidez
* 🔥 Comunicación en tiempo real con Firebase
* 📊 Guardado de historial en Firestore
* 🔘 Botón físico conectado a GPIO

---

## Tecnologías usadas

* Python
* Raspberry Pi GPIO
* Flask
* OpenCV
* Firebase Realtime Database
* Firestore
* Picamera2

---

## Acceso a la cámara

Abrir en el navegador:

```bash
http://<IP-RPI>:5000/
```

Ejemplo:

```bash
http://172.20.10.3:5000/
```

---

## Pines GPIO

| Componente      | GPIO |
| --------------- | ---- |
| Relé luz        | 17   |
| Relé bomba      | 23   |
| Relé filtro     | 24   |
| Servo           | 18   |
| Botón           | 27   |
| Sensor turbidez | 22   |

---

## Ejecutar proyecto

```bash
python3 main.py
```

---

## Notas

* El sensor DS18B20 está comentado porque todavía no funciona correctamente.
* Los relés trabajan en LOW.
* El stream de cámara funciona con Flask + MJPEG.
* Firebase se usa para sincronizar estados en tiempo real.
