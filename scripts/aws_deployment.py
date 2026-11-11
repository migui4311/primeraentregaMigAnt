import argparse
import json
import shlex
import time

import boto3


def setup(session, account, simulator_ip):
    ec2 = session.client("ec2")
    sqs = session.client("sqs")
    sns = session.client("sns")
    db = session.client("dynamodb")
    s3 = session.client("s3")
    vpc, = ec2.describe_vpcs(Filters=[{"Name": "is-default", "Values": ["true"]}])["Vpcs"]
    vpc_id = vpc["VpcId"]
    subnet = ec2.describe_subnets(Filters=[
        {"Name": "vpc-id", "Values": [vpc_id]},
        {"Name": "default-for-az", "Values": ["true"]},
    ])["Subnets"][0]["SubnetId"]
    ami = session.client("ssm").get_parameter(
        Name="/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
    )["Parameter"]["Value"]
    dead = sqs.create_queue(QueueName="v2x-events-dlq")["QueueUrl"]
    dead_arn = sqs.get_queue_attributes(QueueUrl=dead, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    queue = sqs.create_queue(QueueName="v2x-events", Attributes={
        "ReceiveMessageWaitTimeSeconds": "20", "VisibilityTimeout": "60",
        "RedrivePolicy": json.dumps({"deadLetterTargetArn": dead_arn, "maxReceiveCount": 5}),
    })["QueueUrl"]
    topic = sns.create_topic(Name="v2x-alerts")["TopicArn"]
    for table, key in (("v2x-events", "event_id"), ("v2x-alerts", "alert_id")):
        try:
            db.create_table(TableName=table, BillingMode="PAY_PER_REQUEST",
                            AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
                            KeySchema=[{"AttributeName": key, "KeyType": "HASH"}])
        except db.exceptions.ResourceInUseException:
            pass
        db.get_waiter("table_exists").wait(TableName=table)
    bucket = f"v2x-artifacts-{account}-us-east-1"
    if bucket not in {item["Name"] for item in s3.list_buckets()["Buckets"]}:
        s3.create_bucket(Bucket=bucket)
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        name: True for name in ("BlockPublicAcls", "IgnorePublicAcls",
                                "BlockPublicPolicy", "RestrictPublicBuckets")})
    s3.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={"Rules": [
        {"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]})
    ids = {}
    for name in ("v2x-service", "v2x-rsu-1", "v2x-rsu-2"):
        groups = ec2.describe_security_groups(Filters=[
            {"Name": "group-name", "Values": [name]}, {"Name": "vpc-id", "Values": [vpc_id]}
        ])["SecurityGroups"]
        group = groups[0]["GroupId"] if groups else ec2.create_security_group(
            GroupName=name, Description=f"V2X {name}", VpcId=vpc_id)["GroupId"]
        if name != "v2x-service":
            for port, cidr in ((1883, simulator_ip), (8080, "0.0.0.0/0")):
                try:
                    ec2.authorize_security_group_ingress(GroupId=group, IpProtocol="tcp",
                                                         FromPort=port, ToPort=port, CidrIp=cidr)
                except ec2.exceptions.ClientError as error:
                    if error.response["Error"]["Code"] != "InvalidPermission.Duplicate":
                        raise
        reservations = ec2.describe_instances(Filters=[
            {"Name": "tag:Name", "Values": [name]}, {"Name": "vpc-id", "Values": [vpc_id]},
            {"Name": "instance-state-name", "Values": ["pending", "running", "stopped", "stopping"]},
        ])["Reservations"]
        instances = [instance for reservation in reservations for instance in reservation["Instances"]]
        if instances:
            instance, = instances
            instance_id = instance["InstanceId"]
            if instance["State"]["Name"] in {"stopped", "stopping"}:
                ec2.get_waiter("instance_stopped").wait(InstanceIds=[instance_id])
                ec2.start_instances(InstanceIds=[instance_id])
        else:
            instance_id = ec2.run_instances(
                ImageId=ami, InstanceType="t3.micro", MinCount=1, MaxCount=1,
                IamInstanceProfile={"Name": "LabInstanceProfile"},
                MetadataOptions={"HttpTokens": "required", "HttpPutResponseHopLimit": 2},
                NetworkInterfaces=[{"DeviceIndex": 0, "SubnetId": subnet, "Groups": [group],
                                    "AssociatePublicIpAddress": True}],
                TagSpecifications=[{"ResourceType": "instance", "Tags": [{"Key": "Name", "Value": name}]}],
                UserData="#!/bin/bash\nset -e\ndnf install -y docker\nsystemctl enable --now docker\n",
            )["Instances"][0]["InstanceId"]
        ids[name] = instance_id
    print(json.dumps({"bucket": bucket, "instances": ids, "topic": topic, "queue": queue}, indent=2))


def rollout(session, bucket, revision, instances, topic, queue):
    ssm = session.client("ssm")
    pending = {}
    for index, instance in enumerate(instances):
        name = "v2x-rsu" if index else "v2x-service"
        source = shlex.quote(f"s3://{bucket}/releases/{revision}/{name}")
        options = ["-e", f"TOPIC_ARN={topic}", "-e", f"QUEUE_URL={queue}"]
        if index:
            options += ["-e", f"RSU_ID=rsu-{index}", "-p", "1883:1883", "-p", "8080:8080",
                        "-v", "v2x-rsu-state:/state"]
        args = shlex.join(options + [f"{name}:{revision}"])
        health = "curl -fsS http://localhost:8080/health" if index else (
            "test \"$(docker inspect -f '{{.State.Status}} {{.RestartCount}}' v2x-service)\" = 'running 0'")
        commands = [
            "set -eu", "work=$(mktemp -d)", "trap 'rm -rf -- \"$work\"' EXIT", 'cd "$work"',
            f"aws s3 cp {source}.tar.gz {name}.tar.gz",
            f"aws s3 cp {source}.sha256 {name}.sha256",
            f"sha256sum -c {name}.sha256", f"docker load -i {name}.tar.gz",
            f"if docker inspect {name} >/dev/null 2>&1; then docker stop {name}; "
            f"docker rename {name} {name}-previous; fi",
            f"if docker run -d --restart unless-stopped --name {name} {args} && sleep 8 && {health}; then "
            f"docker rm {name}-previous 2>/dev/null || true; else "
            f"docker logs --tail 30 {name} || true; docker rm -f {name} || true; "
            f"if docker inspect {name}-previous >/dev/null 2>&1; then "
            f"docker rename {name}-previous {name}; docker start {name}; fi; exit 1; fi",
        ]
        pending[instance] = ssm.send_command(InstanceIds=[instance],
            DocumentName="AWS-RunShellScript", Parameters={"commands": commands,
                                                            "executionTimeout": ["600"]})["Command"]["CommandId"]
    failed = []
    for _ in range(75):
        for instance, command in list(pending.items()):
            try:
                result = ssm.get_command_invocation(CommandId=command, InstanceId=instance)
            except ssm.exceptions.InvocationDoesNotExist:
                continue
            status = result["Status"]
            if status in {"Pending", "InProgress", "Delayed", "Cancelling"}:
                continue
            print(instance, command, status, result.get("StandardErrorContent", ""))
            if status != "Success":
                failed.append(instance)
            del pending[instance]
        if not pending:
            break
        time.sleep(8)
    if pending or failed:
        raise RuntimeError(f"Failed: {failed}. Still pending: {pending}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile")
    parser.add_argument("--account", default="364733575524")
    commands = parser.add_subparsers(dest="command", required=True)
    provision = commands.add_parser("setup")
    provision.add_argument("--simulator-cidr", required=True)
    deploy = commands.add_parser("deploy")
    deploy.add_argument("--bucket", required=True)
    deploy.add_argument("--revision", required=True)
    deploy.add_argument("--instances", nargs=3, required=True)
    deploy.add_argument("--topic", required=True)
    deploy.add_argument("--queue", required=True)
    args = parser.parse_args()
    session = boto3.Session(profile_name=args.profile, region_name="us-east-1")
    account = session.client("sts").get_caller_identity()["Account"]
    if account != args.account:
        parser.error("AWS identity does not match deployment account")
    if args.command == "setup":
        from ipaddress import IPv4Network
        network = IPv4Network(args.simulator_cidr)
        if network.prefixlen != 32:
            parser.error("Simulator CIDR must identify one IPv4 address")
        setup(session, account, str(network))
    else:
        rollout(session, args.bucket, args.revision, args.instances, args.topic, args.queue)


if __name__ == "__main__":
    main()
