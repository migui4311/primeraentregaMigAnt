import argparse
import json
import random
import time
from datetime import datetime, timezone
from uuid import uuid4

from paho.mqtt import client as mqtt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rsu", nargs=2, required=True, metavar=("HOST1", "HOST2"))
    parser.add_argument("--rate", type=float, default=5)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--duplicate", type=float, default=0)
    args = parser.parse_args()
    if args.rate <= 0 or args.rounds <= 0 or not 0 <= args.duplicate <= 1:
        parser.error("rate and rounds must be positive and duplicate must be between 0 and 1")
    rng = random.Random(args.seed)
    clients = []
    try:
        for vehicle in range(5):
            index = int(vehicle >= 3)
            rsu = f"rsu-{index + 1}"
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"veh-{vehicle + 1}")
            client.on_message = lambda _, __, msg: print(msg.payload.decode(), flush=True)
            client.on_connect = lambda c, _, __, reason, props, rsu=rsu: c.subscribe(
                f"v2x/{rsu}/alerts", qos=1)
            client.connect(args.rsu[index])
            client.loop_start()
            clients.append((client, rsu))
        for cycle in range(args.rounds):
            for i, (client, rsu) in enumerate(clients):
                kind = ("rutina", "frenado brusco", "peligro_carretera")[(cycle + i) % 3]
                event = {"event_id": str(uuid4()), "source_id": f"veh-{i + 1}",
                         "rsu_id": rsu, "event_type": kind,
                         "event_time": datetime.now(timezone.utc).isoformat(),
                         "location": "segmento_1",
                         "payload": {"speed": 0 if kind == "frenado brusco" else 60,
                                     "position": i, "density": 5}}
                for _ in range(1 + (rng.random() < args.duplicate)):
                    result = client.publish(f"v2x/{rsu}/events", json.dumps(event), qos=1)
                    result.wait_for_publish(timeout=5)
                    if not result.is_published():
                        raise RuntimeError("MQTT acknowledgement timed out")
                    print(json.dumps({"outcome": "sent", **event}), flush=True)
                time.sleep(1 / args.rate)
        time.sleep(5)
    finally:
        for client, _ in clients:
            client.disconnect()
            client.loop_stop()


if __name__ == "__main__":
    main()
