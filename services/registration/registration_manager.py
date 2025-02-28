import json
import qrcode
import uuid
from datetime import datetime
from pathlib import Path

class RegistrationManager:
    def __init__(self):
        self.base_dir = Path("/opt/smart-hub/registrations")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.pending_file = self.base_dir / "pending_requests.json"
        self.users_file = self.base_dir / "registered_users.json"
        self._load_data()

    def _load_data(self):
        """Load pending requests and registered users"""
        if not self.pending_file.exists():
            self.pending_requests = {}
        else:
            with open(self.pending_file, 'r') as f:
                self.pending_requests = json.load(f)

        if not self.users_file.exists():
            self.registered_users = {}
        else:
            with open(self.users_file, 'r') as f:
                self.registered_users = json.load(f)

    def _save_data(self):
        """Save pending requests and registered users"""
        with open(self.pending_file, 'w') as f:
            json.dump(self.pending_requests, f, indent=2)
        with open(self.users_file, 'w') as f:
            json.dump(self.registered_users, f, indent=2)

    def generate_registration_qr(self):
        """Generate QR code for device registration"""
        hub_info = {
            "hub_id": self._get_hub_id(),
            "name": self._get_hub_name(),
            "local_address": self._get_local_address(),
            "registration_endpoint": "/api/register"
        }
        
        # Create QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(json.dumps(hub_info))
        qr.make(fit=True)
        
        return qr.make_image(fill_color="black", back_color="white")

    def submit_registration_request(self, request_data):
        """Handle new registration request from user"""
        request_id = str(uuid.uuid4())
        
        request = {
            "id": request_id,
            "username": request_data["username"],
            "public_key": request_data["public_key"],
            "device_name": request_data["device_name"],
            "requested_at": datetime.utcnow().isoformat(),
            "status": "pending"
        }
        
        self.pending_requests[request_id] = request
        self._save_data()
        
        return {
            "request_id": request_id,
            "status": "pending"
        }

    def list_pending_requests(self, admin_token):
        """List all pending registration requests"""
        if not self._verify_admin(admin_token):
            raise Exception("Unauthorized")

        return [
            {
                "id": req_id,
                "username": req["username"],
                "device_name": req["device_name"],
                "requested_at": req["requested_at"]
            }
            for req_id, req in self.pending_requests.items()
            if req["status"] == "pending"
        ]

    def approve_request(self, request_id, admin_token, role="user"):
        """Approve a registration request"""
        if not self._verify_admin(admin_token):
            raise Exception("Unauthorized")

        request = self.pending_requests.get(request_id)
        if not request or request["status"] != "pending":
            raise Exception("Invalid request")

        # Generate access token and encrypt with user's public key
        access_data = self._generate_access_data(request["username"], role)
        encrypted_token = self._encrypt_access_data(
            access_data, 
            request["public_key"]
        )

        # Update request status
        request["status"] = "approved"
        request["approved_at"] = datetime.utcnow().isoformat()
        request["approved_by"] = admin_token["username"]
        request["role"] = role

        # Add to registered users
        self.registered_users[request["username"]] = {
            "username": request["username"],
            "public_key": request["public_key"],
            "role": role,
            "registered_at": datetime.utcnow().isoformat(),
            "approved_by": admin_token["username"]
        }

        self._save_data()
        
        return {
            "request_id": request_id,
            "encrypted_token": encrypted_token
        }

    def deny_request(self, request_id, admin_token, reason=None):
        """Deny a registration request"""
        if not self._verify_admin(admin_token):
            raise Exception("Unauthorized")

        request = self.pending_requests.get(request_id)
        if not request or request["status"] != "pending":
            raise Exception("Invalid request")

        request["status"] = "denied"
        request["denied_at"] = datetime.utcnow().isoformat()
        request["denied_by"] = admin_token["username"]
        request["deny_reason"] = reason

        self._save_data()
        
        return {"status": "denied"}

    def _get_hub_id(self):
        """Get hub identifier"""
        with open("/opt/smart-hub/config/device.json", 'r') as f:
            config = json.load(f)
            return config["device_id"]

    def _verify_admin(self, token):
        """Verify admin token and permissions"""
        # Implement your admin verification logic
        pass

    def _generate_access_data(self, username, role):
        """Generate access token and related data"""
        # Implement your token generation logic
        pass

    def _encrypt_access_data(self, data, public_key):
        """Encrypt access data with user's public key"""
        # Implement encryption logic
        pass