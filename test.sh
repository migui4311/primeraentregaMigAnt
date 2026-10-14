#!/bin/bash
if [ -f "adminalertas.py" ]; then
  echo "Prueba superada: adminalertas.py existe."
  exit 0
else
  echo "Prueba fallida: falta adminalertas.py."
  exit 1
fi