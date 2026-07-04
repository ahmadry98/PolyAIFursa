from dotenv import load_dotenv

load_dotenv()

import os
import boto3

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
AWS_S3_BUCKET = os.environ.get("AWS_S3_BUCKET", "test-bucket")

def download_bytes_from_s3(key: str) -> bytes:
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    response = s3_client.get_object(
        Bucket=AWS_S3_BUCKET,
        Key=key,
    )
    return response["Body"].read()


def upload_file_to_s3(file_path: str, key: str, content_type: str = "image/jpeg") -> str:
    s3_client = boto3.client("s3", region_name=AWS_REGION)
    with open(file_path, "rb") as f:
        s3_client.put_object(
            Bucket=AWS_S3_BUCKET,
            Key=key,
            Body=f,
            ContentType=content_type,
        )
    return key
