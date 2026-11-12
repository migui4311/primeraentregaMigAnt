# V2X deployment

This repository runs five simulated vehicles through two MQTT roadside units
and one cloud consumer. Each RSU runs on its own EC2 instance and sends selected
events to SQS. The consumer records events in DynamoDB and publishes road
hazards to SNS. Both RSUs relay cloud alerts to vehicles. RSUs also raise
local braking alerts and buffer selected events in SQLite while SQS is unavailable.

## Antonio's Learner Lab

Start the lab and configure an AWS CLI profile named `antonio` with all three
temporary credential values. Use `us-east-1`. Run from the repository root.

```powershell
python -m pip install -r requirements.txt
aws sts get-caller-identity --profile antonio
python scripts/aws_deployment.py --profile antonio setup --simulator-cidr YOUR_PUBLIC_IPV4/32
```

The account must be `364733575524`. The setup command prints the bucket, queue URL,
topic ARN and instance IDs. Check that the three hosts appear online in Systems
Manager and Docker is running before pushing.

Create the `antonio-development` GitHub environment and restrict it to
`development_antonio`. Set these variables from the setup output.

| Variable | Value |
| --- | --- |
| `ANTONIO_S3_BUCKET` | Artifact bucket |
| `ANTONIO_EC2_INSTANCE_ID` | Consumer instance ID |
| `ANTONIO_RSU_1_INSTANCE_ID` | RSU 1 instance ID |
| `ANTONIO_RSU_2_INSTANCE_ID` | RSU 2 instance ID |
| `ANTONIO_TOPIC_ARN` | SNS topic ARN |
| `ANTONIO_QUEUE_URL` | SQS queue URL |

Add environment secrets `ANTONIO_AWS_ACCESS_KEY_ID`,
`ANTONIO_AWS_SECRET_ACCESS_KEY` and `ANTONIO_AWS_SESSION_TOKEN`. Refresh all three
when the lab session changes. Push `development_antonio`. Actions builds both
images, stores archives and checksums in S3 under the commit SHA, and deploys
the same images via Systems Manager. The current `main` workflow targets Miguel's
existing S3 setup.

After the first successful rollout, use the current public IP of each RSU to
subscribe it to SNS. Run once for each RSU, substituting its IP and the topic ARN.

```powershell
aws sns subscribe --profile antonio --region us-east-1 --topic-arn TOPIC_ARN --protocol http --notification-endpoint http://RSU_PUBLIC_IP:8080/sns
aws sns list-subscriptions-by-topic --profile antonio --region us-east-1 --topic-arn TOPIC_ARN
```

Verify both subscription ARNs are confirmed. If a lab restart changes a public
IP, subscribe the new endpoint and remove the old subscription. MQTT ingress
is limited to the simulator IP specified during setup. Remove stale MQTT
security group rules when that IP changes.

## Miguel's Learner Lab

Account `991872371561`, branch `development_miguel`, job `deploy-miguel`. No GitHub
variables are needed: the deployment finds the bucket, instances, queue and topic by name.

1. Create the infrastructure once. In the Learner Lab console open **CloudShell** (or use a
   laptop profile and add `--profile miguel` before `--account`):

   ```bash
   git clone -b development_miguel https://github.com/migui4311/primeraentregaMigAnt.git
   cd primeraentregaMigAnt
   pip3 install --user boto3
   python3 scripts/aws_deployment.py --account 991872371561 setup --simulator-cidr YOUR_PUBLIC_IPV4/32
   ```

   Wait a few minutes until the three instances are running and online in Systems Manager.
2. Refresh the repository secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and
   `AWS_SESSION_TOKEN` with the current lab credentials.
3. Push to `development_miguel` or re-run the workflow. `deploy-miguel` publishes the image
   archives to S3, rolls them out through Systems Manager and subscribes both RSUs to SNS
   (old public IPs are unsubscribed). Its log prints the simulator command with the RSU IPs.

## Run and verify

```powershell
python -m unittest discover -s tests
python local_files/coches.py --rsu RSU_1_PUBLIC_IP RSU_2_PUBLIC_IP --rate 5 --rounds 10
```

The simulator sends routine, braking and road-hazard events. Match vehicle logs
to processed event IDs and persisted DynamoDB rows. Check that braking alerts
come from the local RSU and cloud hazard alerts reach both RSUs.

MQTT uses QoS 1. A publisher acknowledgement covers delivery to the broker.
The RSU removes an outbox entry after SQS accepts it. The consumer deletes the
queue message after processing. SQS uses 20-second long polling and a 60-second
visibility timeout, with a dead-letter queue after five receives. A retry can
repeat SNS publication if the process fails between publishing and recording
success. RSUs deduplicate cloud notifications by alert ID.

For the duplication experiment, run with `--duplicate 0` and `--duplicate 0.2`
using the same seed, rate and rounds. Save simulator and consumer output per run.
For component failure, stop the consumer container for 60 seconds during a
longer run, sample SQS queue depth, then start it and record when the backlog
drains. Record measured results in the submission report.

## Measurements

Every consumer log line is JSON: `processed` (with `latency_ms` from the vehicle timestamp
and `queue_ms` from the SQS `SentTimestamp`), `duplicate`, `alert`, `retry`. The RSU logs
`duplicate` when an event ID is still waiting in its outbox. A duplicate that arrives after
the original left the outbox is detected by the consumer through a conditional DynamoDB write
(`status` `processing` → `done`), so the final state stays consistent. Routine duplicates
inside the 5-second window are filtered before deduplication.

`latency_ms` compares the laptop clock with the EC2 clock. Synchronise the laptop first
(Windows: `w32tm /resync`). `queue_ms` only uses AWS clocks.

```bash
python local_files/coches.py --rsu RSU1_IP RSU2_IP --rate 5 --rounds 40 --seed 7 --duplicate 0.2 > sim.log
python scripts/metrics.py --profile miguel logs --since 15m --out consumer.log
python scripts/metrics.py --profile miguel logs --since 15m --instance v2x-rsu-1 --out rsu1.log
python scripts/metrics.py --profile miguel logs --since 15m --instance v2x-rsu-2 --out rsu2.log
python scripts/metrics.py --profile miguel summary --sim sim.log --consumer consumer.log --rsu rsu1.log rsu2.log --dynamodb
```

The summary reports publishes, unique events, duplicates absorbed per RSU and in the cloud,
processed and lost counts per event type and per RSU, retries, cloud alerts, latency
p50/p95/max and the DynamoDB final-state check. For the component-failure experiment, sample
the queue while the consumer is stopped:

```bash
python scripts/metrics.py --profile miguel queue --interval 5 --out queue.csv
```
