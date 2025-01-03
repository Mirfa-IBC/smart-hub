import secrets
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

class AdminSetupManager:
    def __init__(self):
        self.config_dir = Path("/opt/smart-hub/config")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.setup_file = self.config_dir / "admin_setup.json"
        self.admin_setup = None
        self._load_or_create_setup()

    def _generate_setup_code(self):
        """Generate secure setup code during installation"""
        # Generate 16 random bytes and create formatted code
        random_bytes = secrets.token_bytes(12)
        code_int = int.from_bytes(random_bytes, byteorder='big')
        
        # Format as XXXX-YYYY-ZZZZ
        code = format(code_int, '024x').upper()
        return f"{code[:4]}-{code[4:8]}-{code[8:12]}"

    def _load_or_create_setup(self):
        """Load existing or create new admin setup configuration"""
        if not self.setup_file.exists():
            setup_code = self._generate_setup_code()
            hub_id = f"HUB_{secrets.token_hex(6)}"
            
            self.admin_setup = {
                "hub_id": hub_id,
                "setup_code": setup_code,
                "setup_code_hash": hashlib.sha256(setup_code.encode()).hexdigest(),
                "created_at": datetime.utcnow().isoformat(),
                "is_configured": False,
                "code_valid_until": (
                    datetime.utcnow() + timedelta(days=7)
                ).isoformat()
            }
            
            # Save configuration
            with open(self.setup_file, 'w') as f:
                json.dump(self.admin_setup, f, indent=2)
            
            # Print installation information
            self._print_installation_info(hub_id, setup_code)
        else:
            with open(self.setup_file, 'r') as f:
                self.admin_setup = json.load(f)

    def _print_installation_info(self, hub_id, setup_code):
        """Print installation information for operations team"""
        print("\n" + "="*50)
        print("SMART HUB INSTALLATION COMPLETE")
        print("="*50)
        print("\nIMPORTANT: Save this information securely!")
        print("\nHub ID:", hub_id)
        print("Admin Setup Code:", setup_code)
        print("\nThis code will expire in 7 days")
        print("\nShare this information securely with the admin")
        print("="*50 + "\n")

    def verify_setup_code(self, provided_code, is_local=False):
        """Verify admin setup code"""
        if self.admin_setup["is_configured"]:
            return False, "Admin already configured"

        # Check if code has expired
        expiry = datetime.fromisoformat(self.admin_setup["code_valid_until"])
        if datetime.utcnow() > expiry:
            return False, "Setup code has expired"

        # For local setup, we might want to bypass code verification
        if is_local and self._verify_local_network():
            return True, "Local setup verified"

        # Verify provided code
        provided_hash = hashlib.sha256(provided_code.encode()).hexdigest()
        if provided_hash != self.admin_setup["setup_code_hash"]:
            return False, "Invalid setup code"

        return True, "Code verified"

    def _verify_local_network(self):
        """Verify request is coming from local network"""
        # Implement local network verification
        # This could check request IP against local subnet
        pass

    def complete_admin_setup(self, admin_data, is_local=False):
        """Complete admin setup with provided data"""
        # Verify setup is still pending
        if self.admin_setup["is_configured"]:
            raise Exception("Admin already configured")

        # Verify setup code if not local
        if not is_local:
            valid, message = self.verify_setup_code(
                admin_data.get("setup_code", "")
            )
            if not valid:
                raise Exception(message)

        # Save admin configuration
        admin_config = {
            "username": admin_data["username"],
            "public_key": admin_data["public_key"],
            "configured_at": datetime.utcnow().isoformat(),
            "configured_from": "local" if is_local else "remote",
            "role": "admin"
        }

        # Update setup status
        self.admin_setup["is_configured"] = True
        self.admin_setup["configured_at"] = datetime.utcnow().isoformat()
        
        # Save configurations
        with open(self.config_dir / "admin.json", 'w') as f:
            json.dump(admin_config, f, indent=2)
        with open(self.setup_file, 'w') as f:
            json.dump(self.admin_setup, f, indent=2)

        return {
            "status": "success",
            "hub_id": self.admin_setup["hub_id"],
            "configured_at": admin_config["configured_at"]
        }

    def get_setup_status(self):
        """Get current setup status"""
        return {
            "hub_id": self.admin_setup["hub_id"],
            "is_configured": self.admin_setup["is_configured"],
            "setup_expires": self.admin_setup["code_valid_until"]
        }