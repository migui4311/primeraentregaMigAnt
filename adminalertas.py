


import boto3
import json



sqs = boto3.client('sqs', region_name='us-east-1')
queue_name = 'ColaEventos'


try:
    respuesta_url = sqs.get_queue_url(QueueName=queue_name)
    queue_url = respuesta_url['QueueUrl']
    print(f"V2X-SERVICE Iniciado. Escuchando en: {queue_url}")
except Exception as e:
    print(f"Error: No se encuentra la cola '{queue_name}'.")
    exit()

try:
    while True:
            # 2. Recibir mensajes de SQS (WaitTimeSeconds=10 hace 'Long Polling' para no gastar recursos)
            respuesta = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10, # Recibir hasta 10 mensajes de golpe
                WaitTimeSeconds=10
            )

            if 'Messages' in respuesta:
                for mensaje in respuesta['Messages']:
                    recibo_id = mensaje['ReceiptHandle']
                    cuerpo_json = mensaje['Body']
                    
                    # 3. Leer el JSON del vehículo
                    try:
                        datos = json.loads(cuerpo_json)
                        vehiculo = datos.get('source_id', 'Desconocido')
                        tipo_evento = datos.get('event_type', 'rutina')
                        
                      
                        if tipo_evento in ['frenado brusco', 'peligro_carretera']:
                        
                            print(f" ¡ALERTA CRÍTICA GENERADA EN LA NUBE! ")
                            print(f"Motivo: {tipo_evento.upper()} detectado.")
                            print(f"Vehículo implicado: {vehiculo}")
                            print(f"Ubicación: {datos.get('location')}")

                        else:
                            print(f"Evento de rutina procesado para {vehiculo}.")
                            
                    except json.JSONDecodeError:
                        print("Error: Se recibió un mensaje que no es JSON válido.")

                    # 5. Eliminar el mensaje de la cola una vez procesado para no repetirlo
                    sqs.delete_message(
                        QueueUrl=queue_url,
                        ReceiptHandle=recibo_id
                    )




except KeyboardInterrupt:
    print("\nServicio V2X detenido manualmente.")






