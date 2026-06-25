import os
import boto3

AWS_REGION = os.environ["AWS_REGION"]
AWS_S3_BUCKET = os.environ["AWS_S3_BUCKET"]

s3_client = boto3.client("s3", region_name=AWS_REGION)


def upload_bytes_to_s3(data: bytes, key: str, content_type: str = "image/jpeg") -> str:
    s3_client.put_object(
        Bucket=AWS_S3_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key
