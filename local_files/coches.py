

import boto3
import json
import time
import uuid
import random
from datetime import datetime, timezone



sqs = boto3.client('sqs', region_name='us-east-1')

# Inicializar cliente SQS
sqs = boto3.client('sqs', region_name='us-east-1')

queue_name = 'ColaEventos' # nombre de la cola que ya lo decidiré

try:

    respuesta_url = sqs.get_queue_url(QueueName=queue_name)

    queue_url = respuesta_url['QueueUrl'] # obtener la URL asignada a la cola

    print(f"URL de la cola: {queue_url}")

except Exception as e:

    print(f"Error al obtener la URL de la cola: {queue_name} ")
    exit()



vehiculos = ['veh-1', 'veh-2', 'veh-3', 'veh-4', 'veh-5']


tipos_evento = ['rutina', 'frenado brusco', 'peligro_carretera']


tasa_envio_segundos = 2.0 # Tasa de eventos configurable

try:
    while True:
        n_vehiculo = random.choice(vehiculos) # Selecciona un vehículo aleatorio de la lista
        n_evento = random.choices(tipos_evento, weights = [0.9,0.05,0.05])[0] # Selecciona un tipo de evento aleatorio de la lista
        if n_evento == 'rutina':
            velocidad = random.randint(60,120) # Genera una velocidad aleatoria entre 60 y 120 km/h para eventos de rutina
        elif n_evento == 'frenado brusco':
            velocidad = 0 # Genera una velocidad aleatoria entre
        elif n_evento == 'peligro_carretera':
            velocidad = random.randint(10,50) # Genera una velocidad aleatoria entre 0 y 120 km/h para eventos de peligro en la carretera

        evento = {
                    "event_id": f"evt-{uuid.uuid4().hex[:8]}",
                    "source_id": n_vehiculo,
                    "event_type": n_evento,
                    "event_time": datetime.now(timezone.utc).isoformat(),
                    "location": f"segmento_carretera_{random.randint(1, 3)}",
                    "payload": {
                        "speed": velocidad
                    }
                }


        mensaje = json.dumps(evento)

        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=mensaje
            )


        print(f"[{evento['event_time']}] Enviado -> Vehículo: {n_vehiculo} | Evento: {n_evento}")


        time.sleep(tasa_envio_segundos)  # Espera antes de enviar el siguiente evento



except KeyboardInterrupt:
    print("Interrupción del usuario. Saliendo del programa.")


