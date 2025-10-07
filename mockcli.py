import boto3
from botocore.config import Config

# --- Proxy Configuration (Centralized) ---
# NOTE: Replace with your actual proxy details and credentials
PROXY_HOST = "your.proxy.server.com:8080"
PROXY_USER = "DOMAIN\\user"
PROXY_PASS = "secure_password"
HTTPS_PROXY_URL = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}"

PROXY_CONFIG = Config(
    proxies={
        'https': HTTPS_PROXY_URL
    },
    # Optional: Increase connection/read timeouts if on a slow or complex network
    # connect_timeout=10, 
    # read_timeout=60,
)

# --------------------------------------------------------------------------

def execute_aws_command(service_name: str, method_name: str, **kwargs) -> dict:
    """
    Dynamically executes a Boto3 API call with a predefined proxy configuration.

    Args:
        service_name: The name of the AWS service (e.g., 's3', 'ec2', 'iam').
        method_name: The Boto3 client method name (e.g., 'list_buckets', 
                     'describe_regions'). NOTE: This is NOT the full CLI command.
        **kwargs: Keyword arguments for the API method (e.g., Bucket='my-bucket').

    Returns:
        The dictionary response from the AWS API call.
    """
    try:
        # 1. Create a Boto3 client dynamically, applying the proxy configuration.
        client = boto3.client(
            service_name,
            config=PROXY_CONFIG
        )
        
        # 2. Get the specific method (API action) from the client object by name.
        # This is the "flexible" part, avoiding explicit pre-defined calls.
        api_method = getattr(client, method_name)
        
        # 3. Execute the method, passing any required parameters (**kwargs).
        response = api_method(**kwargs)
        
        return response

    except Exception as e:
        print(f"Error executing AWS command: {e}")
        # Re-raise the exception or return a structured error, depending on your needs
        raise

# --------------------------------------------------------------------------
# --- Examples of usage ---

# Example 1: Equivalent to `aws s3 list-buckets`
s3_response = execute_aws_command(
    service_name='s3',
    method_name='list_buckets'
)

print("--- S3 List Buckets (via Proxy) ---")
for bucket in s3_response.get('Buckets', []):
    print(f"Bucket Name: {bucket['Name']}, Creation Date: {bucket['CreationDate']}")
print("-" * 30)

# Example 2: Equivalent to `aws ec2 describe-regions --all-regions`
ec2_response = execute_aws_command(
    service_name='ec2',
    method_name='describe_regions',
    AllRegions=True  # Boto3 uses PascalCase for API parameters
)

print("--- EC2 Describe Regions (via Proxy) ---")
for region in ec2_response.get('Regions', [])[:3]:
    print(f"Region Name: {region['RegionName']}")
print("-" * 30)

# Example 3: Equivalent to `aws iam list-users --max-items 2`
iam_response = execute_aws_command(
    service_name='iam',
    method_name='list_users',
    MaxItems=2
)

print("--- IAM List Users (via Proxy) ---")
for user in iam_response.get('Users', []):
    print(f"User Name: {user['UserName']}, ARN: {user['Arn']}")
print("-" * 30)
