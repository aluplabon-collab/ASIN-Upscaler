import subprocess
import hashlib
import hmac
import base64
import sys
import os

# Secret key for HMAC signing - HARDCODED. 
# in a real scenario, this should be obfuscated better, but for this level it's fine.
SECRET_KEY = b"BloodTek_LLC_Powered_By_Some_Indivisuals_At_Home_2026"

def get_machine_code():
    """Retrieves a unique machine code based on hardware UUID."""
    machine_uuid = None
    
    # Method 1: WMIC (Legacy, might fail on Win11)
    try:
        cmd = "wmic csproduct get uuid"
        # creationflags=0x08000000 starts process without window
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
        lines = output.split('\n')
        for line in lines:
            line = line.strip()
            if line and "UUID" not in line and len(line) > 20: # simple validation
                machine_uuid = line
                break
    except:
        pass

    # Method 2: Registry (Windows only fallback)
    if not machine_uuid and sys.platform == 'win32':
        try:
             import winreg
             registry_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) # type: ignore
             value, _ = winreg.QueryValueEx(registry_key, "MachineGuid") # type: ignore
             winreg.CloseKey(registry_key) # type: ignore
             machine_uuid = value.strip()
        except:
             pass

    # Method 3: macOS (ioreg)
    if not machine_uuid and sys.platform == 'darwin':
        try:
            cmd = "ioreg -d2 -c IOPlatformExpertDevice | awk -F\\\" '/IOPlatformUUID/{print $(NF-1)}'"
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().strip()
            if output:
                machine_uuid = output
        except:
             pass

    # Method 4: Linux (machine-id)
    if not machine_uuid and sys.platform.startswith('linux'):
        try:
             # Try /etc/machine-id or /var/lib/dbus/machine-id
             for p in ['/etc/machine-id', '/var/lib/dbus/machine-id']:
                 if os.path.exists(p):
                     with open(p, 'r') as f:
                         machine_uuid = f.read().strip()
                     if machine_uuid: break
        except:
             pass

    if not machine_uuid:
        # Fallback to hostname if getting HWID fails (not ideal but better than crash)
        import socket
        machine_uuid = socket.gethostname()

    return machine_uuid

def generate_license_key(machine_code):
    """Generates the expected license key based on the secret."""
    if not machine_code:
        return ""
    
    # HMAC-SHA256
    signature = hmac.new(SECRET_KEY, machine_code.encode(), hashlib.sha256).digest()
    # Base64 encode and take first 25 chars
    key = base64.urlsafe_b64encode(signature).decode().strip()[:25] # type: ignore
    return key

def get_app_data_path():
    """Returns a writable directory for application data."""
    home = os.path.expanduser("~")
    app_name = "ImageProcessor"
    
    if sys.platform == 'win32':
        base_path = os.environ.get('APPDATA', os.path.join(home, 'AppData', 'Roaming'))
    elif sys.platform == 'darwin':
        base_path = os.path.join(home, 'Library', 'Application Support')
    else:
        # Linux / Unix
        base_path = home
        app_name = ".amazon_scraper"

    full_path = os.path.join(base_path, app_name)
    if not os.path.exists(full_path):
        os.makedirs(full_path, exist_ok=True)
        
    return full_path

def validate_license(machine_code, input_key):
    """Validates the input key against the machine code."""
    expected_key = generate_license_key(machine_code)
    # Constant time comparison to prevent timing attacks (though overkill here)
    return hmac.compare_digest(expected_key, input_key)
