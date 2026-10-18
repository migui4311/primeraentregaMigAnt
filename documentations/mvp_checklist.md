# MVP completion checklist

Baseline: `0787b61`, shared by `main` and `development_antonio` on 18 October 2026 before this documentation commit. This file describes pending work; no listed code changes have been implemented by the documentation update. Use [submission_report.md](submission_report.md) for the submission narrative.

## What exists and what is missing

| Area | Current implementation/evidence | TBD / acceptance criterion |
| --- | --- | --- |
| Five vehicles | One simulator randomly selects five IDs; historical logs include all five | TBD: deterministic demonstration covering all five with recorded counts |
| Event path | Direct SQS producer and consumer; historical EC2 logs | TBD: fresh simulator → SQS → assessed EC2 image demonstration |
| Queue | Code and inspected AWS use `ColaEventos` | TBD: consistently use assignment name `v2x-events`, or document instructor-approved exception |
| Alerts | Braking and road hazards print alerts | TBD: controlled scenario and evidence; resolve Dashboard Interface wording |
| Container | Dockerfile exists; two stopped containers inspected on 14 October | TBD: running assessed container, recorded image identifier and restart/boot behavior |
| CI tests | Only a file-presence test | TBD: committed behavioral tests passing in CI |
| CI build/publication | Source files uploaded to S3 | TBD: build image and publish versioned archive to S3 or image to ECR; verify retrieval/start on EC2 |
| Deployment documentation | Reconstructed procedure and historical infrastructure review | TBD: validate commands against assessed setup and record identifiers/date |
| Report | Submission draft with actual findings and explicit gaps | TBD: authors, assessed version, final results, CI reference and rendered five-page check |

## Proposed implementation order

1. Make producer and consumer importable for offline tests; validate event objects and define deliberate rejection/retry behavior.
2. Add configurable queue/region/rate and a finite deterministic demo covering five vehicles and hazard conditions. Use full UUIDs for future duplicate detection.
3. Add meaningful tests, then build and publish the image in CI. Keep deployment credentials/publication out of pull-request validation.
4. Run the published image on EC2, decide restart behavior, and capture a controlled demonstration with the agreed alert display.
5. Fill the report's `TBD` fields with actual results or explicit remaining limitations. Render the final report and check the page count.

These implementation choices are proposals. Unpinned dependencies, inadequate validation, duplicate alerts and missing restart behavior are known limitations, not features already fixed.

## Test/evidence completion fields

| Evidence | Value |
| --- | --- |
| Test command / test revision | TBD |
| Automated test total / passed / failed | TBD |
| CI run URL and assessed commit | TBD |
| Published image URI or archive key + digest | TBD |
| Deployment command/run record | TBD |
| Smoke-test date and duration | TBD |
| Sent / processed / rejected / alert counts | TBD |
| Five vehicle IDs and both alert conditions observed | TBD |
| Relevant logs or screenshots | TBD |
| Alert-display acceptance | TBD |
| Final report rendered page count | TBD |

Reviewer probes and historical logs are summarized in the report. Do not present them as a committed test suite or a fresh measured experiment. Do not invent measurements to complete this table.

## Final-system work, separate from MVP

- Two Dockerized RSUs on EC2, MQTT vehicle communication and routing to assigned RSUs.
- Edge validation/filtering or aggregation, at least one local alert, and documented cloud-disconnection buffering/retries.
- SNS `v2x-alerts` HTTPS delivery to both RSUs and MQTT forwarding to vehicles.
- Persistence, documented event/alert schemas, retry/acknowledgement choices and idempotency where required.
- Repeatable automated EC2 deployment of the assessed version.
- At least one delivery-anomaly or edge-disconnection experiment, plus one component-failure or load-increase experiment, with the assignment's required measurements.

The final system is due 15 November 2026, with assessment/defense on 16 November. These items should not obscure the immediate MVP test/build/image-publication gaps.
