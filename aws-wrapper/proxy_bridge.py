import socket
import select
import ctypes
import ctypes.wintypes
import base64
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# --- Windows API Definitions ---
winhttp = ctypes.windll.winhttp
secur32 = ctypes.windll.secur32

class WINHTTP_PROXY_INFO(ctypes.Structure):
    _fields_ = [("dwAccessType", ctypes.wintypes.DWORD),
                ("lpszProxy", ctypes.wintypes.LPWSTR),
                ("lpszProxyBypass", ctypes.wintypes.LPWSTR)]

class WINHTTP_CURRENT_USER_IE_PROXY_CONFIG(ctypes.Structure):
    _fields_ = [("fAutoDetect", ctypes.wintypes.BOOL),
                ("lpszAutoConfigUrl", ctypes.wintypes.LPWSTR),
                ("lpszProxy", ctypes.wintypes.LPWSTR),
                ("lpszProxyBypass", ctypes.wintypes.LPWSTR)]

class WINHTTP_AUTOPROXY_OPTIONS(ctypes.Structure):
    _fields_ = [("dwFlags", ctypes.wintypes.DWORD),
                ("dwAutoDetectFlags", ctypes.wintypes.DWORD),
                ("lpszAutoConfigUrl", ctypes.wintypes.LPWSTR),
                ("lpvReserved", ctypes.c_void_p),
                ("dwReserved", ctypes.wintypes.DWORD),
                ("fAutoLogonIfChallenged", ctypes.wintypes.BOOL)]

class SecBuffer(ctypes.Structure):
    _fields_ = [("cbBuffer", ctypes.c_ulong), ("BufferType", ctypes.c_ulong), ("pvBuffer", ctypes.c_void_p)]

class SecBufferDesc(ctypes.Structure):
    _fields_ = [("ulVersion", ctypes.c_ulong), ("cBuffers", ctypes.c_ulong), ("pBuffers", ctypes.POINTER(SecBuffer))]

# --- Helper Functions ---

def get_kerberos_token(proxy_host):
    """Generates a Negotiate (Kerberos) token using Windows SSPI."""
    cred_handle = ctypes.c_longlong()
    # Acquire credentials handle for the current logged-in user
    secur32.AcquireCredentialsHandleW(None, "Negotiate", 1, None, None, None, None, ctypes.byref(cred_handle), None)
    
    out_buffer = ctypes.create_string_buffer(12000)
    s_buf = SecBuffer(12000, 2, ctypes.addressof(out_buffer))
    s_desc = SecBufferDesc(0, 1, ctypes.pointer(s_buf))
    
    ctx_handle = ctypes.c_longlong()
    ctx_attr = ctypes.wintypes.DWORD()
    spn = f"HTTP/{proxy_host}"
    
    # Initialize security context to get the outbound token
    status = secur32.InitializeSecurityContextW(
        ctypes.byref(cred_handle), None, ctypes.c_wchar_p(spn),
        0x00000010, 0, 0, None, 0, ctypes.byref(ctx_handle),
        ctypes.byref(s_desc), ctypes.byref(ctx_attr), None
    )
    
    if status in [0, 0x00090312]: # SEC_E_OK or SEC_I_CONTINUE_NEEDED
        token = base64.b64encode(out_buffer[:s_buf.cbBuffer]).decode('ascii')
        return f"Negotiate {token}"
    return None

def resolve_proxy(target_url):
    """Robustly resolves proxy using WinHTTP (PAC, WPAD, or Static)."""
    if not target_url.startswith('http'):
        target_url = f"https://{target_url}"
    
    session = winhttp.WinHttpOpen(ctypes.c_wchar_p("PyBridge"), 0, None, None, 0)
    try:
        ie_config = WINHTTP_CURRENT_USER_IE_PROXY_CONFIG()
        winhttp.WinHttpGetIEProxyConfigForCurrentUser(ctypes.byref(ie_config))
        
        options = WINHTTP_AUTOPROXY_OPTIONS()
        options.fAutoLogonIfChallenged = True
        
        # Determine PAC vs WPAD
        if ie_config.lpszAutoConfigUrl:
            options.dwFlags = 0x2 # WINHTTP_AUTOPROXY_CONFIG_URL
            options.lpszAutoConfigUrl = ie_config.lpszAutoConfigUrl
        elif ie_config.fAutoDetect:
            options.dwFlags = 0x1 # WINHTTP_AUTOPROXY_AUTO_DETECT
            options.dwAutoDetectFlags = 0x3 # DHCP & DNS
        else:
            # Fallback to static proxy if defined
            return ie_config.lpszProxy.split(';')[0] if ie_config.lpszProxy else "DIRECT"

        info = WINHTTP_PROXY_INFO()
        if winhttp.WinHttpGetProxyForUrl(session, ctypes.c_wchar_p(target_url), ctypes.byref(options), ctypes.byref(info)):
            return info.lpszProxy.split(';')[0] if info.lpszProxy else "DIRECT"
        return "DIRECT"
    finally:
        winhttp.WinHttpCloseHandle(session)

# --- Proxy Handler ---

class RobustBridge(BaseHTTPRequestHandler):
    def handle_request(self):
        target_url = self.path if self.command != 'CONNECT' else f"https://{self.path}"
        proxy_res = resolve_proxy(target_url)
        
        # Parse result
        if proxy_res == "DIRECT":
            is_direct = True
            if self.command == 'CONNECT':
                p_host, _, p_port = self.path.partition(':')
            else:
                u = urlparse(target_url)
                p_host, p_port = u.hostname, (u.port or 80)
        else:
            is_direct = False
            proxy_res = proxy_res.replace("http://", "").replace("https://", "")
            p_host, _, p_port = proxy_res.partition(':')
            p_port = int(p_port) if p_port else 8080

        try:
            upstream = socket.create_connection((p_host, int(p_port)))
            
            if self.command == 'CONNECT':
                if is_direct:
                    self.send_response(200)
                    self.end_headers()
                else:
                    auth = get_kerberos_token(p_host)
                    headers = f"Proxy-Authorization: {auth}\r\n" if auth else ""
                    req = f"CONNECT {self.path} HTTP/1.1\r\nHost: {self.path}\r\n{headers}\r\n"
                    upstream.sendall(req.encode())
                    # Check for proxy's 200 OK
                    resp = upstream.recv(4096)
                    if b"200" not in resp:
                        self.send_error(502, f"Proxy Auth Failed: {resp.decode(errors='ignore')}")
                        return
                    self.send_response(200)
                    self.end_headers()
                self._relay(self.connection, upstream)
            else:
                # HTTP GET/POST handling
                auth = get_kerberos_token(p_host) if not is_direct else ""
                req = f"{self.command} {target_url} HTTP/1.1\r\n"
                for k, v in self.headers.items():
                    if k.lower() not in ['proxy-authorization', 'proxy-connection']:
                        req += f"{k}: {v}\r\n"
                if auth: req += f"Proxy-Authorization: {auth}\r\n"
                req += "\r\n"
                upstream.sendall(req.encode())
                self._relay(self.connection, upstream)
                
        except Exception as e:
            self.send_error(502, f"Bridge error: {e}")

    def _relay(self, client, upstream):
        sockets = [client, upstream]
        while True:
            r, _, _ = select.select(sockets, [], [], 20)
            if not r: break
            for s in r:
                data = s.recv(16384)
                if not data: return
                (upstream if s is client else client).sendall(data)

    do_GET = do_POST = do_PUT = do_DELETE = do_CONNECT = handle_request

if __name__ == "__main__":
    print("Bridge running at http://127.0.0.1:3128")
    HTTPServer(('127.0.0.1', 3128), RobustBridge).serve_forever()
