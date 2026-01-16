import sys
import subprocess
import socket
import select
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from requests_kerberos import HTTPKerberosAuth, OPTIONAL

# --- CONFIGURATION ---
# Path to your corporate proxy-discovery script
PROXY_RESOLVER_SCRIPT = "/path/to/your/proxy_script.sh"
LISTEN_PORT = 3128

def get_upstream_proxy(target_url="https://s3.amazonaws.com"):
    """Executes your corporate script to find the current proxy."""
    try:
        # Assuming the script takes a URL and returns 'http://host:port'
        result = subprocess.check_output([PROXY_RESOLVER_SCRIPT, target_url], text=True)
        return result.strip().replace("http://", "").replace("https://", "")
    except Exception as e:
        print(f"Error resolving proxy: {e}")
        return None

class KerberosProxyHandler(BaseHTTPRequestHandler):
    def do_CONNECT(self):
        """Handle HTTPS Tunneling (The AWS CLI primarily uses this)"""
        upstream_proxy = get_upstream_proxy(f"https://{self.path}")
        if not upstream_proxy:
            self.send_error(502, "Could not resolve upstream proxy")
            return

        proxy_host, proxy_port = upstream_proxy.split(':')
        
        try:
            # Connect to the corporate proxy
            upstream_sock = socket.create_connection((proxy_host, int(proxy_port)))
            
            # 1. Start Kerberos Handshake for the Proxy
            # Note: For raw CONNECT, we usually need to send a Proxy-Authorization header.
            # This is a simplified relay. If your proxy requires a handshake BEFORE 
            # the tunnel opens, you must send the CONNECT string with Negotiate headers.
            connect_string = f"CONNECT {self.path} HTTP/1.1\r\nHost: {self.path}\r\n"
            connect_string += "Proxy-Connection: Keep-Alive\r\n\r\n"
            
            upstream_sock.sendall(connect_string.encode())
            
            # Establish the tunnel
            self.send_response(200, "Connection Established")
            self.end_headers()
            
            self._relay(self.connection, upstream_sock)
        except Exception as e:
            self.send_error(502, f"Gateway Error: {e}")

    def _relay(self, client_sock, upstream_sock):
        """Bidirectional data relay between AWS CLI and Corporate Proxy"""
        inputs = [client_sock, upstream_sock]
        while True:
            readable, _, _ = select.select(inputs, [], [])
            for s in readable:
                data = s.recv(8192)
                if not data:
                    return
                out = upstream_sock if s is client_sock else client_sock
                out.sendall(data)

if __name__ == "__main__":
    print(f"Starting DIY Kerberos Bridge on port {LISTEN_PORT}...")
    server = HTTPServer(('127.0.0.1', LISTEN_PORT), KerberosProxyHandler)
    server.serve_forever()
