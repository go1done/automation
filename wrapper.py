#!/usr/bin/env python3
import boto3
import sys
import json
from botocore.exceptions import ClientError
from requests_kerberos import HTTPKerberosAuth, REQUIRED
import argparse

# --- Configuration ---
# 1. SET YOUR PROXY HERE:
PROXY_HOST_PORT = "http://your.kerberos.proxy.server:8080" # <-- **CHANGE THIS**

# Define the proxy settings dictionary expected by Boto3/requests
PROXY_DEFINITIONS = {
    'http': PROXY_HOST_PORT,
    'https': PROXY_HOST_PORT
}

# --- Kerberos Proxy Patching ---

class KerberosProxyHandler:
    """
    A class that acts as a Boto3 event handler to inject Kerberos 
    proxy authentication into the underlying 'requests' session.
    """
    def __init__(self, proxies):
        self._proxies = proxies

    def __call__(self, session, **kwargs):
        """Called when a new requests session is created by Boto3/Botocore."""
        session.proxies = self._proxies
        # Inject the Kerberos Auth handler for the PROXY
        session.auth = HTTPKerberosAuth(
            mutual_authentication=REQUIRED,
            force_preemptive=True
        )
        return session

def initialize_kerberos_proxy():
    """Sets up the global Boto3 session to use the Kerberos proxy."""
    try:
        boto3.setup_default_session()
        default_session = boto3.DEFAULT_SESSION
        # Register the custom handler to the 'http-session-created' event.
        default_session.events.register(
            'http-session-created',
            KerberosProxyHandler(PROXY_DEFINITIONS)
        )
        # print(f"✅ Kerberos proxy configuration applied to Boto3.")
    except ImportError:
        print("❌ Error: The 'requests-kerberos' library is required.")
        print("Please run: pip install requests-kerberos")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error during proxy setup: {e}")
        sys.exit(1)

# --- Dynamic AWS CLI to Boto3 Mapper ---

def normalize_cli_to_boto(cli_name):
    """Converts 'list-buckets' to 'list_buckets' and similar argument names."""
    return cli_name.replace('-', '_')

def parse_cli_args_to_boto_dict(cli_args):
    """
    Converts a flat list of CLI arguments into a Boto3 Python dictionary.
    Handles --param value and infers some Boto3 PascalCase conversion.
    
    NOTE: This is a simplified parser and will fail on complex list/JSON inputs.
    """
    boto_params = {}
    i = 0
    while i < len(cli_args):
        arg = cli_args[i]
        
        if arg.startswith('--'):
            param_key_cli = arg[2:]
            
            # Simple PascalCase conversion: my-key -> MyKey
            param_key_boto = ''.join(word.capitalize() for word in param_key_cli.split('-'))
            
            # Check for value (i.e., next argument doesn't start with '--')
            if i + 1 < len(cli_args) and not cli_args[i+1].startswith('--'):
                param_value = cli_args[i+1]
                boto_params[param_key_boto] = param_value
                i += 2
            else:
                # Assume boolean flag if no value (e.g., --dry-run)
                boto_params[param_key_boto] = True 
                i += 1
        else:
            i += 1
            
    # The 'Region' parameter is handled separately in the client initialization
    boto_params.pop('Region', None)
    return boto_params

def cmd_boto_dynamic(cli_args):
    """
    Main function to parse CLI arguments, configure Kerberos, and execute the Boto3 API call.
    """
    if len(cli_args) < 2:
        print("Usage: ./cmd <service> <command> [options...]")
        print("Example
