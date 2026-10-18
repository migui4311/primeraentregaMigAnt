# AWS deployment review and recreation handoff

Observed on 14 October 2026 in `us-east-1`. This document supports [the submission report](submission_report.md).

## Scope and related documentation

This is a historical review of the deployed application baseline at commit `0787b6130863b2598e88b99a09bb66db7a729e16`. It is not a live status report. The [submission report](submission_report.md) describes the current code and marks missing evidence with `TBD`; the [MVP checklist](mvp_checklist.md) tracks proposed work.

A separate personal AWS recreation handoff is retained outside Git in the workspace notes. This repository document is self-contained for the deployment findings and reconstruction outline; it does not require those external notes to be read.

## Verified deployment

- EC2: `t3.micro`, Amazon Linux 2023 x86_64, AMI `ami-004d1eaf8eaa0107d`; 8 GiB gp3 root volume; default public VPC/subnet; public IPv4; `LabInstanceProfile` containing `LabRole`.
- Metadata: IMDSv2 required, endpoint enabled, response hop limit 2. No key pair or user data. Systems Manager is online; read-only inspection commands succeeded.
- Network: default internet-gateway route and default allow-all network ACL. Security group allows all protocols from one specific IPv4 `/32`, with all IPv4 outbound. Destination access must use the intended client IP or SSM-only access.
- Queue: `ColaEventos`, standard, visibility 30 seconds, retention four days, no delay, maximum message size 1 MiB, SQS-managed encryption, no redrive policy. Queue-default polling wait is zero; the consumer specifies 10 seconds.
- S3: private source bucket in `us-east-1`, all public-access blocks enabled, BucketOwnerEnforced, SSE-S3, no bucket policy, versioning unset. Four source/build files are stored at the root. No image archive or ECR repository was found in the inspected scope.
- Docker 25.0.16 is active but disabled at boot. Both containers are stopped and have restart policy `no`.
- Container: image `v2x-service`, working directory `/app`, command `python -u adminalertas.py`, default networking, no ports/mounts, no application/AWS environment overrides, `json-file` logging.

The source instance is named `v2x-service-ec2`. Source image ID: `sha256:53b48c4b7f9fdad7cd10725f9ed0808e155ad84a201613f4efea66f92722065b`. This is an identifier, not a remotely pullable image; its archive was not exported.

## Application evidence

Both stopped containers' consumer and requirements hashes match the repository. The S3 Dockerfile, consumer and requirements match byte-for-byte; the shell test matches after newline normalization.

Historical logs show connection to `ColaEventos`, routine processing across all five vehicle IDs across the excerpts, and both braking and road-hazard alerts. `wonderful_kilby` exited 0 and includes a manual-stop message. `charming_keldysh` exited 137; its cause was not determined. These observations establish earlier processing, not continuous availability or a fresh controlled end-to-end test.

The inspection did not restart containers, change application configuration, or receive/delete SQS messages. Systems Manager created normal command records while running inspection commands. Credential values were not captured in these files.

## Reconstruction procedure

1. Verify the destination account and its permitted `LabInstanceProfile`. Use its own resource IDs, credentials, and default public subnet.
2. Create `ColaEventos` with the recorded attributes. The assignment fix to `v2x-events` requires both scripts and the queue to change together.
3. Create a uniquely named private S3 bucket and upload the four root source/build files from the recorded revision.
4. Launch the equivalent EC2 host with IMDSv2/hop limit 2 and destination lab profile; connect through Systems Manager.
5. Install/start Docker, download the files, build `docker build -t v2x-service .`, then start `docker run -d --name v2x-service --restart=no v2x-service`.
6. Run the laptop simulator with destination credentials and capture a controlled event/alert demonstration.

For a reliable running copy, enable Docker at boot and use the `unless-stopped` container restart policy. These are explicit improvements over the source. Rebuilding the unpinned Python image/dependency does not guarantee the source image's exact digest. Destination deployment has not been executed or validated yet. The repository contains the application sources; the submission report includes build/run commands. TBD: execute and record the complete assessed deployment procedure.

## CI and remaining work

The current workflow tests only file existence and copies source to S3; it does not build/publish an image or update EC2. Use a separate destination workflow/environment or fork to avoid redirecting the collaborator's deployment. Configure destination secrets separately and refresh expiring lab credentials as needed.

Remaining MVP work: behavioral tests, CI image build/publication, queue-name alignment, a fresh demo, alert-display acceptance, and documented restart behavior. Lab-managed IAM/SNS/Lambda infrastructure and unrelated S3 website content are outside the V2X recreation. Final-system RSU/MQTT/SNS/persistence work remains separate.
