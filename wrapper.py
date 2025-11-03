#!/usr/bin/env python3
import boto3
import subprocess
import sys
from requests_kerberos import HTTPKerberosAuth, REQUIRED

# NOTE: You MUST install 'requests-kerberos' for this to work:
# pip install boto3 requests-kerberos

# --- Configuration ---
# 1. SET YOUR PROXY HERE:
PROXY_HOST_PORT = "http://your.kerberos.proxy.server:8080" # <-- **CHANGE THIS**

# Define the proxy settings dictionary expected by Boto3/requests
PROXY_DEFINITIONS = {
    'http': PROXY_HOST_PORT,
    'https': PROXY_HOST_PORT 
}

# --- Boto3/Kerberos Setup ---

class KerberosProxyHandler:
    """
    A class that acts as a Boto3 event handler to inject Kerberos 
    proxy authentication into the underlying 'requests' session.
    """
    def __init__(self, proxies):
        self._proxies = proxies

    def __call__(self, session, **kwargs):
        """Called when a new requests session is created by Boto3/Botocore."""
        
        # 1. Apply the proxy definitions to the session
        session.proxies = self._proxies
        
        # 2. Inject the Kerberos Auth handler for the PROXY
        # This tells the session to use Kerberos authentication when talking to the proxy.
        session.auth = HTTPKerberosAuth(
            mutual_authentication=REQUIRED,
            force_preemptive=True
        )
        
        # Ensure proxies are correctly set again (redundancy for clarity)
        session.proxies['http'] = PROXY_HOST_PORT
        session.proxies['https'] = PROXY_HOST_PORT
        
        return session

def initialize_kerberos_proxy():
    """Sets up the global Boto3 session to use the Kerberos proxy."""
    try:
        # Get the default Boto3 session
        boto3.setup_default_session()
        default_session = boto3.DEFAULT_SESSION

        # Register the custom handler to the 'http-session-created' event.
        # This ensures the proxy is configured whenever Boto3 makes an HTTP call.
        default_session.events.register(
            'http-session-created',
            KerberosProxyHandler(PROXY_DEFINITIONS)
        )
        print(f"✅ Kerberos proxy configuration applied to Boto3 session: {PROXY_HOST_PORT}")
    except ImportError:
        print("❌ Error: The 'requests-kerberos' library is required.")
        print("Please run: pip install requests-kerberos")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error during Boto3 setup: {e}")
        sys.exit(1)

# --- CLI Implementation ---

def run_aws_cli_command(args):
    """
    Executes the 'aws' command using the system's binary, leveraging the 
    patched Boto3 configuration in the Python environment.
    """
    if not args:
        print(f"Usage: {sys.argv[0]} s3 ls")
        sys.exit(1)

    # 1. Initialize Boto3 session (to inject the proxy logic)
    initialize_kerberos_proxy()

    # 2. Construct the full command array
    full_command = ['aws'] + args
    
    print(f"-> Executing AWS CLI Command: {' '.join(full_command)}")
    
    # 3. Execute the command
    try:
        # subprocess.run executes the 'aws' binary. Since the binary 
        # executes in the same Python environment, the Boto3 session 
        # (used by AWS CLI) will pick up the Kerberos proxy config.
        result = subprocess.run(
            full_command,
            check=True,
            text=True,
            capture_output=False, # Stream output directly to the console
            env=None # Keep environment clean; Boto3 handles the config
        )
        # Exit with the AWS CLI's return code
        sys.exit(result.returncode)

    except subprocess.CalledProcessError as e:
        # Command ran but returned a non-zero exit code (e.g., AWS auth error)
        print(f"AWS CLI command failed with error code {e.returncode}.")
        sys.exit(e.returncode)
    except FileNotFoundError:
        # The 'aws' binary itself wasn't found
        print("\n❌ Error: The 'aws' command was not found.")
        print("Please ensure the AWS CLI is installed and in your system's PATH.")
        sys.exit(127)

if __name__ == "__main__":
    # Pass all arguments *after* the script name to the AWS CLI
    run_aws_cli_command(sys.argv[1:])
