import os
import json
import secrets
import qrcode
from datetime import datetime
from pathlib import Path
import jwt

class DeviceRegistration:
    def __init__(self):
        self.config_dir = Path("/opt/smart-hub/config")
        self.device_config = self.config_dir / "device.json"
        self.registration_key = None
        self.device_id = None
        self.initialize()

    def initialize(self):
        """Initialize device configuration"""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        if not self.device_config.exists():
            # Generate new device ID and registration key
            self.device_id = f"hub_{secrets.token_hex(6)}"
            self.registration_key = secrets.token_urlsafe(32)
            
            config = {
                "device_id": self.device_id,
                "registration_key": self.registration_key,
                "created_at": datetime.now(),
                "registered": False,
                "owner": None,
                "name": None
            }
            
            with open(self.device_config, 'w') as f:
                json.dump(config, f, indent=2)
        else:
            with open(self.device_config, 'r') as f:
                config = json.load(f)
                self.device_id = config["device_id"]
                self.registration_key = config["registration_key"]

    def generate_registration_qr(self):
        """Generate QR code for device registration"""
        registration_data = {
            "device_id": self.device_id,
            "key": self.registration_key,
            "type": "smart-hub",
            "local_address": self._get_local_address()
        }
        
        # Create QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(json.dumps(registration_data))
        qr.make(fit=True)
        
        # Save QR code
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(self.config_dir / "registration_qr.png")
        
        return registration_data

    def _get_local_address(self):
        """Get device's local IP address"""
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "unknown"
        finally:
            s.close()

    def register_device(self, registration_data):
        """Register device with user"""
        try:
            with open(self.device_config, 'r') as f:
                config = json.load(f)
            
            if config["registered"]:
                return False, "Device already registered"
            
            if registration_data["key"] != self.registration_key:
                return False, "Invalid registration key"
            
            config["registered"] = True
            config["owner"] = registration_data["user_id"]
            config["name"] = registration_data["device_name"]
            config["registered_at"] = datetime.utcnow().isoformat()
            
            with open(self.device_config, 'w') as f:
                json.dump(config, f, indent=2)
            
            # Generate device access token
            access_token = self.generate_device_token(config)
            
            return True, {
                "device_id": self.device_id,
                "access_token": access_token,
                "local_address": self._get_local_address()
            }
        
        except Exception as e:
            return False, str(e)

    def generate_device_token(self, config):
        """Generate JWT token for device access"""
        secret = secrets.token_hex(32)
        
        # Save secret for token verification
        with open(self.config_dir / "jwt_secret", 'w') as f:
            f.write(secret)
        
        token = jwt.encode({
            "device_id": config["device_id"],
            "owner": config["owner"],
            "type": "device_access",
            "created_at": datetime.utcnow().isoformat()
        }, secret, algorithm="HS256")
        
        return token

    def verify_access(self, token):
        """Verify device access token"""
        try:
            with open(self.config_dir / "jwt_secret", 'r') as f:
                secret = f.read().strip()
            
            with open(self.device_config, 'r') as f:
                config = json.load(f)
            
            decoded = jwt.decode(token, secret, algorithms=["HS256"])
            
            return (decoded["device_id"] == config["device_id"] and 
                   decoded["owner"] == config["owner"])
        except Exception:
            return False