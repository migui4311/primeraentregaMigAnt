



FROM python:3.12-slim

# Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar el archivo de requisitos y las dependencias
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar nuestro código del servicio
COPY adminalertas.py .

# Ejecutar el servicio (el parámetro -u es para que los prints salgan directos en la consola)
CMD ["python", "-u", "adminalertas.py"]








