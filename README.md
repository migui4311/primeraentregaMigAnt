# V2X cloud-processing MVP

A Python vehicle simulator sends events directly to Amazon SQS. A Dockerized Python consumer processes them and prints routine messages or hazard alerts. This is the Deliverable 1 architecture; the RSU/MQTT/SNS layers belong to the complete system.

## Documentation

- [Submission report](documentations/submission_report.md): design, implementation, deployment, tests/results, and DevOps. Explicit `TBD` fields identify missing evidence or implementation.
- [MVP completion checklist](documentations/mvp_checklist.md): what exists and what must be finished, separated from final-system work.
- [AWS deployment review](documentations/aws_review.md): infrastructure and container observations from 14 October 2026, plus reconstruction guidance.

The application baseline is commit `0787b6130863b2598e88b99a09bb66db7a729e16`, shared by `main` and `development_antonio` when checked on 18 October 2026. This documentation does not implement the pending changes. AWS observations are historical, not a current health check.

## Repository layout

```text
local_files/coches.py          Laptop vehicle simulator
adminalertas.py               SQS consumer and console alerts
Dockerfile                   Consumer container build
requirements.txt             Runtime dependency (boto3)
test.sh                      Existing file-presence check
.github/workflows/deploy.yml  Source-file publication to S3
documentations/              Report, checklist, and deployment evidence
```

Both Python scripts currently use `us-east-1` and queue `ColaEventos`. The existing workflow uploads source files; it does not build/publish a container image or deploy EC2. Follow the report's deployment prerequisites before running the application. Keep AWS credentials outside the repository.
