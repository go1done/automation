import socket
import select
import ctypes
import ctypes.wintypes
import base64
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- Windows API Definitions (WinHTTP & SSPI) ---
winhttp = ctypes.windll.winhttp
secur32 = ctypes.windll.secur32

# WinHTTP Structures
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

# SSPI Structures (Kerberos)
class SecBuffer(ctypes.Structure):
    _fields_ = [("cbBuffer", ctypes.c_ulong), ("BufferType", ctypes.c_ulong), ("pvBuffer", ctypes.c_void_p)]
class SecBufferDesc(ctypes.Structure):
    _fields_ = [("ulVersion", ctypes.c_ulong), ("cBuffers", ctypes.c_ulong), ("pBuffers", ctypes.POINTER(SecBuffer))]

# --- Core Logic Functions ---

def resolve_pac_robust(target_url):
    """Uses WinHTTP to resolve the actual proxy from the system's PAC configuration."""
    session = winhttp.WinHttpOpen(ctypes.c_wchar_p("PyBridge"), 0, None, None, 0)
    try:
        ie_config = WINHTTP_CURRENT_USER_IE_PROXY_CONFIG()
        winhttp.WinHttpGetIEProxyConfigForCurrentUser(ctypes.byref(ie_config))
        
        pac_url = ie_config.lpszAutoConfigUrl
        if not pac_url:
            return None # Direct connection or static proxy needed
            
        options = WINHTTP_AUTOPROXY_OPTIONS()
        options.dwFlags = 0x00000002 # WINHTTP_AUTOPROXY_CONFIG_URL
        options.lpszAutoConfigUrl = pac_url
        options.fAutoLogonIfChallenged = True
        
        info = WINHTTP_PROXY_INFO()
        if winhttp.WinHttpGetProxyForUrl(session, ctypes.c_wchar_p(target_url), ctypes.byref(options), ctypes.byref(info)):
            proxy = info.lpszProxy
            if proxy:
                # Returns 'host:port' (handles multiple proxies by taking the first)
                return proxy.split(';')[0].strip().replace("http://", "")
    finally:
        winhttp.WinHttpCloseHandle(session)
    return None

def get_kerberos_token(proxy_host):
    """Generates a Negotiate (Kerberos/NTLM) token via Windows SSPI."""
    cred_handle = ctypes.c_longlong()
    secur32.AcquireCredentialsHandleW(None, "Negotiate", 1, None, None, None, None, ctypes.byref(cred_handle), None)
    
    out_buffer = ctypes.create_string_buffer(12000)
    s_buf = SecBuffer(12000, 2, ctypes.addressof(out_buffer))
    s_desc = SecBufferDesc(0, 1, ctypes.pointer(s_buf))
    
    ctx_handle = ctypes.c_longlong()
    ctx_attr = ctypes.wintypes.DWORD()
    spn = f"HTTP/{proxy_host}"
    
    status = secur32.InitializeSecurityContextW(
        ctypes.byref(cred_handle), None, ctypes.c_wchar_p(spn),
        0x00000010, 0, 0, None, 0, ctypes.byref(ctx_handle),
        ctypes.byref(s_desc), ctypes.byref(ctx_attr), None
    )
    
    if status in [0, 0x00090312]: # SEC_E_OK or SEC_I_CONTINUE_NEEDED
        return "Negotiate " + base64.b64encode(out_buffer[:s_buf.cbBuffer]).decode('ascii')
    return None

class RobustBridgeHandler(BaseHTTPRequestHandler):
    def handle_request(self):
        target_url = self.path if self.command != 'CONNECT' else f"https://{self.path}"
        proxy_str = resolve_pac_robust(target_url)
        
        if not proxy_str:
            self.send_error(502, "PAC Resolution failed to find a proxy.")
            return

        p_host, _, p_port = proxy_str.partition(':')
        p_port = int(p_port) if p_port else 8080

        try:
            upstream = socket.create_connection((p_host, p_port))
            auth_token = get_kerberos_token(p_host)
            auth_header = f"Proxy-Authorization: {auth_token}\r\n" if auth_token else ""

            if self.command == 'CONNECT':
                req = f"CONNECT {self.path} HTTP/1.1\r\nHost: {self.path}\r\n{auth_header}\r\n"
                upstream.sendall(req.encode())
                if b"200" in upstream.recv(4096):
                    self.send_response(200)
                    self.end_headers()
                    self._relay(self.connection, upstream)
            else:
                full_path = self.path if self.path.startswith('http') else f"http://{self.headers['Host']}{self.path}"
                req = f"{self.command} {full_path} HTTP/1.1\r\n"
                for k, v in self.headers.items():
                    if k.lower() not in ['proxy-authorization', 'proxy-connection']:
                        req += f"{k}: {v}\r\n"
                req += auth_header + "\r\n"
                upstream.sendall(req.encode())
                self._relay(self.connection, upstream)
        except Exception as e:
            self.send_error(502, f"Bridge Error: {e}")

    def _relay(self, client, upstream):
        sockets = [client, upstream]
        while True:
            r, _, _ = select.select(sockets, [], [], 10)
            if not r: break
            for s in r:
                data = s.recv(16384)
                if not data: return
                (upstream if s is client else client).sendall(data)

    do_GET = do_POST = do_PUT = do_DELETE = do_CONNECT = handle_request

if __name__ == "__main__":
    print("Robust Windows PAC + Kerberos Bridge starting on 127.0.0.1:3128...")
    HTTPServer(('127.0.0.1', 3128), RobustBridgeHandler).serve_forever()
