# V2X monitoring and alerting: MVP report

**Authors:** TBD - full names and student identifiers.

**Submission date:** 18 October 2026. **Assessed revision/image:** TBD.

**Document status:** submission draft describing the existing implementation; replace every `TBD` with implementation details or honest limitations before submission. Target: maximum five rendered pages. **Final page-count check:** TBD.

## 1. Design and implementation

The MVP implements cloud-side event processing before the edge layer is introduced. A laptop simulator sends JSON events directly to SQS; V2X-SERVICE consumes them in a Docker container intended to run on EC2 and generates console alerts. Direct simulator-to-SQS communication is explicitly permitted for Deliverable 1. RSUs, MQTT and SNS alert delivery are final-system work.

```text
Laptop simulator -> SQS ColaEventos -> EC2 / V2X-SERVICE -> console alerts
GitHub Actions -> source files in S3
```

The reviewed code is commit `0787b6130863b2598e88b99a09bb66db7a729e16`, common to `main` and `development_antonio` before the documentation changes. Both scripts hardcode region `us-east-1` and queue `ColaEventos`. **TBD:** align the queue and code with the assignment's `v2x-events` name.

`local_files/coches.py` represents five vehicles (`veh-1` to `veh-5`) in one process. Every two seconds it selects one vehicle and an event type: `rutina` (90%), `frenado brusco` (5%), or `peligro_carretera` (5%). The rate is approximately 0.5 events/second in total and is editable only in the source. Routine speeds range from 60–120 km/h, braking speed is zero, and hazard speeds range from 10–50 km/h. Random selection does not guarantee all five vehicles or an alert in a short run.

| JSON field | Implementation |
| --- | --- |
| `event_id` | `evt-` plus eight UUID hexadecimal characters; not used for deduplication |
| `source_id` | Selected vehicle ID |
| `event_type` | One of the three types above |
| `event_time` | Source-generated UTC ISO timestamp |
| `location` | One of three synthetic road segments |
| `payload.speed` | Speed in km/h |

`adminalertas.py` requests up to ten messages with a ten-second long poll. It prints a critical alert for braking or road hazards and a routine message otherwise, then deletes each handled message. Alerts include type, vehicle and location. No alert returns to the laptop; there is no SNS publication, persistence, API or dashboard in the code.

The current validation is limited: malformed JSON is logged and deleted, missing fields receive defaults, and valid non-object JSON can crash the consumer. Duplicate hazards generate duplicate alerts. **TBD:** add explicit validation and document rejection/retry/acknowledgement behavior. **TBD:** confirm whether console output satisfies the MVP's Dashboard Interface wording or implement the required display.

## 2. Deployment procedure

The Dockerfile uses `python:3.12-slim`, installs unpinned `boto3`, copies the consumer into `/app`, and starts `python -u adminalertas.py`. It excludes the laptop simulator from the image. The build recipe exists, but dependency/base-image versions are not fully pinned.

Inspection on 14 October found a running `t3.micro` EC2 host with Amazon Linux 2023, an 8 GiB gp3 root volume, `LabInstanceProfile`, IMDSv2 required and hop limit 2. SQS had 30-second visibility, four-day retention, SQS-managed encryption and no redrive policy. The private S3 deployment bucket contained source/build files. Docker was active but disabled at boot; both application containers were stopped with restart policy `no`. These observations do not establish service availability on submission day.

A reconstructed manual procedure for the existing code is:

1. Verify the target AWS account and region. Create/verify `ColaEventos`, a private artifact bucket, and EC2 with the permitted lab role and outbound AWS connectivity.
2. Upload/download `Dockerfile`, `requirements.txt`, `adminalertas.py`, and `test.sh`; install/start Docker on EC2. The role must permit queue lookup, receive and delete, and any required S3 reads.
3. From the build directory on EC2, execute:

```sh
docker build -t v2x-service .
docker run -d --name v2x-service --restart=no v2x-service
docker logs --tail 50 v2x-service
```

4. On the laptop, configure AWS session credentials outside Git, with queue lookup/send permissions, then execute from the repository root:

```sh
python -m pip install -r requirements.txt
python local_files/coches.py
```

5. Verify consumer output and stop the simulator after recording evidence. Use a fresh container name or deliberately manage an existing container before repeating `docker run`.

These commands reconstruct the current setup; they were not executed as a fresh deployment during review. **TBD:** record the tested deployment commands, target identifiers, image tag/digest and date. **TBD:** decide Docker boot enablement and container restart policy. **TBD:** replace manual image building with retrieval of the CI-published image for the assessed version. See [AWS review](aws_review.md) for supporting details.

## 3. Tests and results

The only committed test, `test.sh`, verifies that `adminalertas.py` exists. It does not test event processing. Reviewer-run offline probes on 14 October replaced boto3 with a fake SQS client; they did not contact AWS and are not a committed regression suite.

| Offline check | Observed result |
| --- | --- |
| Parse both Python files | Syntax valid |
| Routine event plus both hazard types | Three deletions, two alerts |
| Malformed JSON | Error logged; message deleted |
| JSON array `[]` | Unhandled `AttributeError` |
| Empty object `{}` | Accepted as routine and deleted |
| Repeated hazard with identical event ID | Two alerts; no deduplication |
| First intercepted simulator send | Six expected top-level fields present |

Historical EC2 log excerpts showed queue connection, routine processing across all five vehicle IDs across two containers, and both alert types. Consumer/requirements hashes matched the repository; S3 source matched too, allowing for shell-script line endings. This supports earlier operation but provides no controlled counts, latency results or fresh end-to-end demonstration.

**TBD - automated tests:** commit behavioral tests for routine/hazard cases, invalid inputs, mixed batches and AWS failure/deletion behavior; record command, test count and pass/fail result.

**TBD - AWS smoke test:** record date, assessed commit/image, five-vehicle coverage, duration, sent/processed/alert counts and log evidence.

**TBD - reproducible scenarios:** ensure a finite demo produces known vehicles and hazards. No throughput or latency values are claimed without measurements.

## 4. DevOps pipeline

`.github/workflows/deploy.yml` runs on pushes and pull requests targeting `main`. It checks out code, executes `test.sh`, configures AWS credentials, synchronizes the repository to S3 excluding `.git`/`.github`, and lists the uploaded consumer file. Secrets are `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, `AWS_REGION`, and `S3_BUCKET_NAME`; no values belong in this report.

The workflow does not build Docker, publish an image archive/ECR image, or update EC2. Source upload alone does not satisfy the MVP image-publication requirement. **TBD:** add behavioral tests, image build and versioned publication to the chosen S3/ECR destination; keep publication on trusted pushes and validation on pull requests. **TBD:** record a successful CI run URL, artifact identifier and evidence that EC2 runs that artifact. Complete automated EC2 rollout is final-system work.

## 5. Remaining scope

The existing code demonstrates the core producer/consumer and automatic-alert logic, with historical cloud execution evidence. Submission completion still requires the items marked `TBD`, especially tested image publication and a current demonstration. The detailed [MVP checklist](mvp_checklist.md) separates these from final-system requirements: two RSUs, MQTT, local edge alerts/buffering, SNS return path, persistence, automated deployment and the two required controlled experiments.

Requirement basis: assignment update dated 6 October 2026, Deliverable 1 on page 4; the team additionally supplied the maximum-five-page report requirement. The supporting review/checklist are working documentation and are not intended to be appended to the five-page submission report.
