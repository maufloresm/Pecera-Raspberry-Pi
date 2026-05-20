import sys
import time
import signal
from time import sleep
from threading import Thread
from datetime import datetime

import cv2
import board
import RPi.GPIO as GPIO
from gpiozero import Button, DigitalInputDevice
from flask import Flask, Response

import firebase_admin
from firebase_admin import credentials, db, firestore

# ================================================================
#  PINES GPIO
# ================================================================

RELE_LUZ    = 17
RELE_BOMBA  = 23
RELE_FILTRO = 24

SERVO_PIN       = 18
BUTTON_PIN      = 27
TURBIDITY_PIN   = 22

# DS18B20 (deshabilitado — sensor no operativo aún)
# DS18B20_PIN = 4   # GPIO4 es el pin 1-Wire por defecto en RPi

# ================================================================
#  FIREBASE — ajusta la ruta al JSON y la URL de tu proyecto
# ================================================================

PATH_CRED = '/home/raspiot/Documentos/iot 2026-2/Lab08/appiotv2-firebase-adminsdk-fbsvc-5972dccbc0.json'
URL_DB    = 'https://appiotv2-default-rtdb.firebaseio.com/'

# Nodos Realtime Database
REF_HOME    = 'pecera'
REF_LUCES   = 'luces'
REF_BOTONES = 'botones'
REF_SENSORES= 'sensores'

# ================================================================
#  FLASK (stream de cámara)
# ================================================================

flask_app = Flask(__name__)

# ================================================================
#  CONFIGURACIÓN GPIO
# ================================================================

GPIO.setmode(GPIO.BCM)

GPIO.setup(RELE_LUZ,    GPIO.OUT)
GPIO.setup(RELE_BOMBA,  GPIO.OUT)
GPIO.setup(RELE_FILTRO, GPIO.OUT)
GPIO.setup(SERVO_PIN,   GPIO.OUT)

# Relés apagados al inicio (HIGH = OFF con relé activo en LOW)
GPIO.output(RELE_LUZ,    GPIO.HIGH)
GPIO.output(RELE_BOMBA,  GPIO.HIGH)
GPIO.output(RELE_FILTRO, GPIO.HIGH)

# Servo PWM 50 Hz
servo_pwm = GPIO.PWM(SERVO_PIN, 50)
servo_pwm.start(0)

# Botón y sensor de turbidez (gpiozero)
BUTTON       = Button(BUTTON_PIN, pull_up=True, bounce_time=0.2)
TURBIDITY    = DigitalInputDevice(TURBIDITY_PIN, pull_up=False)


# ================================================================
#  CÁMARA
# ================================================================

def init_camera():
    """Inicializa la cámara con picamera2; devuelve la instancia o None."""
    try:
        from picamera2 import Picamera2
        cam = Picamera2()
        cam.configure(cam.create_preview_configuration(main={"size": (640, 480)}))
        cam.start()
        print("✅ Cámara iniciada")
        return cam
    except Exception as e:
        print(f"⚠️  Cámara no disponible: {e}")
        return None

picam2 = init_camera()


def generate_frames():
    """Generador de frames MJPEG para Flask."""
    while True:
        if picam2 is None:
            sleep(1)
            continue
        frame = picam2.capture_array()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        ret, buffer = cv2.imencode('.jpg', frame)
        if not ret:
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')


@flask_app.route('/video_feed')
def video_feed():
    return Response(generate_frames(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@flask_app.route('/')
def index():
    """Página mínima para ver la cámara en el navegador."""
    return """
    <html>
    <head>
        <title>Pecera Inteligente — Cámara</title>
        <style>
            body { background:#111; display:flex; justify-content:center;
                   align-items:center; height:100vh; margin:0; }
            img  { border: 3px solid #00aaff; border-radius: 8px; }
            h2   { color:#00aaff; text-align:center; font-family:sans-serif; }
        </style>
    </head>
    <body>
        <div>
            <h2>🐠 Pecera Inteligente — Live</h2>
            <img src="/video_feed" width="640" height="480"/>
        </div>
    </body>
    </html>
    """


# ================================================================
#  CLASE PRINCIPAL IOT
# ================================================================

class PeceraIOT:

    # --------------------------------------------------------
    #  INIT
    # --------------------------------------------------------

    def __init__(self):

        # — Firebase —
        cred = credentials.Certificate(PATH_CRED)
        firebase_admin.initialize_app(cred, {'databaseURL': URL_DB})

        self.rtdb          = db.reference(REF_HOME)
        self.firestore_db  = firestore.client()

        self._init_rtdb()

        # — Referencias Realtime DB —
        luces             = self.rtdb.child(REF_LUCES)
        self.ref_luz      = luces.child('luz_sala')
        self.ref_bomba    = luces.child('bomba_oxigeno')
        self.ref_filtro   = luces.child('filtro_agua')
        self.ref_servo    = luces.child('servo_angulo')     # ángulo del alimentador

        botones              = self.rtdb.child(REF_BOTONES)
        self.ref_pulsador    = botones.child('pulsador_a')

        sensores             = self.rtdb.child(REF_SENSORES)
        self.ref_turbidez    = sensores.child('turbidez')
        # self.ref_temp      = sensores.child('temperatura')  # DS18B20 — comentado

        # — Estados en memoria —
        self.luz_state    = False
        self.bomba_state  = False
        self.filtro_state = False
        self.btn_locked   = False

    # --------------------------------------------------------
    #  ESTRUCTURA INICIAL REALTIME DB
    # --------------------------------------------------------

    def _init_rtdb(self):
        self.rtdb.set({
            'luces': {
                'luz_sala':      False,
                'bomba_oxigeno': False,
                'filtro_agua':   False,
                'servo_angulo':  45          # posición inicial del alimentador
            },
            'botones': {
                'pulsador_a': False
            },
            'sensores': {
                'turbidez': {
                    'estado': 0,
                    'texto':  'Agua clara'
                },
                # 'temperatura': {             # DS18B20 — comentado
                #     'valor_c': None,
                #     'texto':   'Sin lectura'
                # }
            }
        })
        print("✅ Realtime DB inicializada")

    # --------------------------------------------------------
    #  RELÉS
    # --------------------------------------------------------

    def _apply_relays(self):
        GPIO.output(RELE_LUZ,    GPIO.LOW if self.luz_state    else GPIO.HIGH)
        GPIO.output(RELE_BOMBA,  GPIO.LOW if self.bomba_state  else GPIO.HIGH)
        GPIO.output(RELE_FILTRO, GPIO.LOW if self.filtro_state else GPIO.HIGH)
        print(f"  Luz={self.luz_state}  Bomba={self.bomba_state}  Filtro={self.filtro_state}")

    # --------------------------------------------------------
    #  SERVO (alimentador)
    # --------------------------------------------------------

    def mover_servo(self, angulo: int):
        """Mueve el servo al ángulo indicado (0-180°)."""
        angulo = max(0, min(180, int(angulo)))
        duty = 2 + (angulo / 18)
        servo_pwm.ChangeDutyCycle(duty)
        sleep(0.5)
        servo_pwm.ChangeDutyCycle(0)
        print(f"🐟 Alimentador → {angulo}°")

    # --------------------------------------------------------
    #  BOTÓN FÍSICO
    # --------------------------------------------------------

    def _pulsador_on(self):
        print("🟢 Botón presionado")
        if not self.btn_locked:
            self.btn_locked   = True
            self.luz_state    = not self.luz_state
            self._apply_relays()
            self.ref_luz.set(self.luz_state)
        self.ref_pulsador.set(True)

    def _pulsador_off(self):
        print("🔴 Botón liberado")
        self.btn_locked = False
        self.ref_pulsador.set(False)

    def run_botones(self):
        BUTTON.when_pressed  = self._pulsador_on
        BUTTON.when_released = self._pulsador_off
        while True:
            sleep(1)

    # --------------------------------------------------------
    #  TURBIDEZ → Realtime DB  +  Firestore (histórico)
    # --------------------------------------------------------

    def run_turbidez(self):
        while True:
            estado = TURBIDITY.value                          # 0 = clara, 1 = turbia
            texto  = "Agua turbia" if estado == 1 else "Agua clara"
            ahora  = datetime.now()

            print(f"💧 {texto}")

            # — Realtime DB (estado actual) —
            self.ref_turbidez.set({
                'estado': estado,
                'texto':  texto
            })

            # — Firestore (histórico con fecha y hora) —
            self.firestore_db.collection('turbidez_historial').add({
                'estado':    estado,
                'texto':     texto,
                'fecha':     ahora.strftime('%Y-%m-%d'),
                'hora':      ahora.strftime('%H:%M:%S'),
                'timestamp': ahora                           # tipo datetime nativo
            })

            sleep(10)   # guarda en Firestore cada 10 s (ajusta a tu gusto)

    # --------------------------------------------------------
    #  DS18B20 — TEMPERATURA (comentado, sensor no operativo)
    # --------------------------------------------------------

    # def _leer_ds18b20(self) -> float | None:
    #     """Lee temperatura del sensor DS18B20 (1-Wire en GPIO4)."""
    #     try:
    #         import glob
    #         base = '/sys/bus/w1/devices/'
    #         device_folder = glob.glob(base + '28*')[0]
    #         device_file   = device_folder + '/w1_slave'
    #         with open(device_file, 'r') as f:
    #             lines = f.readlines()
    #         if lines[0].strip()[-3:] == 'YES':
    #             equals_pos = lines[1].find('t=')
    #             if equals_pos != -1:
    #                 return float(lines[1][equals_pos + 2:]) / 1000.0
    #     except Exception as e:
    #         print(f"⚠️  DS18B20: {e}")
    #     return None
    #
    # def run_temperatura(self):
    #     while True:
    #         temp = self._leer_ds18b20()
    #         if temp is not None:
    #             texto = f"{temp:.1f} °C"
    #             print(f"🌡️  Temperatura: {texto}")
    #             self.ref_temp.set({'valor_c': temp, 'texto': texto})
    #         else:
    #             print("🌡️  Sin lectura de temperatura")
    #         sleep(5)

    # --------------------------------------------------------
    #  FIREBASE MONITOR (Realtime DB → GPIO)
    # --------------------------------------------------------

    def run_firebase_monitor(self):
        last = {'luz': None, 'bomba': None, 'filtro': None, 'servo': None}

        while True:
            luz   = self.ref_luz.get()
            bomba = self.ref_bomba.get()
            filtro= self.ref_filtro.get()
            servo = self.ref_servo.get()

            changed = False

            if luz    != last['luz']:
                self.luz_state    = bool(luz);    last['luz']    = luz;    changed = True
            if bomba  != last['bomba']:
                self.bomba_state  = bool(bomba);  last['bomba']  = bomba;  changed = True
            if filtro != last['filtro']:
                self.filtro_state = bool(filtro); last['filtro'] = filtro; changed = True

            if changed:
                self._apply_relays()

            if servo is not None and servo != last['servo']:
                self.mover_servo(servo)
                last['servo'] = servo

            sleep(0.3)


# ================================================================
#  MAIN
# ================================================================

def main():
    print("🐠 Pecera Inteligente — Iniciando...")

    pecera = PeceraIOT()

    # Hilos de lectura / monitoreo
    Thread(target=pecera.run_firebase_monitor, daemon=True).start()
    Thread(target=pecera.run_botones,          daemon=True).start()
    Thread(target=pecera.run_turbidez,         daemon=True).start()
    # Thread(target=pecera.run_temperatura,    daemon=True).start()  # DS18B20 — comentado

    # Servidor Flask (cámara) en hilo separado
    Thread(
        target=lambda: flask_app.run(host='0.0.0.0', port=5000, threaded=True),
        daemon=True
    ).start()

    print("📹 Stream de cámara disponible en http://<IP-RPi>:5000/")
    print("🔥 Conectado a Firebase — esperando eventos...")

    signal.pause()   # mantiene el proceso vivo; Ctrl+C para salir


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Programa detenido por el usuario")
    finally:
        servo_pwm.stop()
        GPIO.cleanup()
        if picam2:
            picam2.close()
        print("✅ GPIO y cámara liberados")