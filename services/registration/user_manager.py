import json
import secrets
import bcrypt
from pathlib import Path
from datetime import datetime, timedelta
from enum import Enum
import jwt
from typing import Dict, List, Optional

class UserRole(Enum):
    OWNER = "owner"       # Full access, can manage users
    ADMIN = "admin"       # Full access to devices and automation
    USER = "user"         # Basic control access
    GUEST = "guest"       # Temporary access, limited control

class Permission(Enum):
    MANAGE_USERS = "manage_users"
    MANAGE_DEVICES = "manage_devices"
    CONTROL_DEVICES = "control_devices"
    VIEW_ONLY = "view_only"
    MANAGE_AUTOMATION = "manage_automation"

class UserManager:
    def __init__(self):
        self.base_dir = Path("/opt/smart-hub/users")
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.users_file = self.base_dir / "users.json"
        self.tokens_file = self.base_dir / "tokens.json"
        self.jwt_secret = self._get_or_create_jwt_secret()
        self._load_users()

    def _get_or_create_jwt_secret(self) -> str:
        secret_file = self.base_dir / "jwt_secret"
        if not secret_file.exists():
            secret = secrets.token_hex(32)
            secret_file.write_text(secret)
        return secret_file.read_text().strip()

    def _load_users(self):
        if not self.users_file.exists():
            self.users = {}
        else:
            with open(self.users_file, 'r') as f:
                self.users = json.load(f)

    def _save_users(self):
        with open(self.users_file, 'w') as f:
            json.dump(self.users, f, indent=2)

    def create_initial_owner(self, username: str, password: str) -> Dict:
        """Create the first owner account during setup"""
        if self.users:
            raise Exception("Initial owner already exists")

        return self.create_user(
            username=username,
            password=password,
            role=UserRole.OWNER,
            created_by="system"
        )

    def create_user(self, username: str, password: str, role: UserRole, 
                   created_by: str, expiry_days: Optional[int] = None) -> Dict:
        """Create a new user"""
        if username in self.users:
            raise Exception("User already exists")

        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode(), salt)
        
        user = {
            "username": username,
            "password": hashed.decode(),
            "role": role.value,
            "created_at": datetime.utcnow().isoformat(),
            "created_by": created_by,
            "permissions": self._get_role_permissions(role),
            "devices": {},  # Device-specific permissions
            "expiry": None if not expiry_days else 
                     (datetime.utcnow() + timedelta(days=expiry_days)).isoformat()
        }
        
        self.users[username] = user
        self._save_users()
        return self.generate_token(username)

    def _get_role_permissions(self, role: UserRole) -> List[str]:
        """Get permissions for a role"""
        permissions = {
            UserRole.OWNER: [p.value for p in Permission],
            UserRole.ADMIN: [
                Permission.MANAGE_DEVICES.value,
                Permission.CONTROL_DEVICES.value,
                Permission.MANAGE_AUTOMATION.value
            ],
            UserRole.USER: [
                Permission.CONTROL_DEVICES.value
            ],
            UserRole.GUEST: [
                Permission.VIEW_ONLY.value
            ]
        }
        return permissions.get(role, [])

    def authenticate(self, username: str, password: str) -> Optional[Dict]:
        """Authenticate user and return token"""
        user = self.users.get(username)
        if not user:
            return None

        if user.get("expiry") and datetime.fromisoformat(user["expiry"]) < datetime.utcnow():
            return None

        if bcrypt.checkpw(password.encode(), user["password"].encode()):
            return self.generate_token(username)
        return None

    def generate_token(self, username: str) -> Dict:
        """Generate JWT token for user"""
        user = self.users[username]
        expiry = datetime.utcnow() + timedelta(days=7)
        
        token_data = {
            "username": username,
            "role": user["role"],
            "permissions": user["permissions"],
            "exp": expiry.timestamp()
        }
        
        token = jwt.encode(token_data, self.jwt_secret, algorithm="HS256")
        
        return {
            "token": token,
            "expires": expiry.isoformat(),
            "username": username,
            "role": user["role"],
            "permissions": user["permissions"]
        }

    def verify_token(self, token: str) -> Optional[Dict]:
        """Verify JWT token and return user data"""
        try:
            data = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            username = data["username"]
            user = self.users.get(username)
            
            if not user:
                return None
                
            if user.get("expiry") and datetime.fromisoformat(user["expiry"]) < datetime.utcnow():
                return None
                
            return data
        except:
            return None

    def set_device_permission(self, username: str, device_id: str, 
                            permissions: List[str], set_by: str) -> bool:
        """Set device-specific permissions for user"""
        if username not in self.users:
            return False
            
        setter = self.users.get(set_by)
        if not setter or setter["role"] not in [UserRole.OWNER.value, UserRole.ADMIN.value]:
            return False
            
        self.users[username]["devices"][device_id] = {
            "permissions": permissions,
            "set_by": set_by,
            "set_at": datetime.utcnow().isoformat()
        }
        self._save_users()
        return True

    def check_permission(self, username: str, permission: str, 
                        device_id: Optional[str] = None) -> bool:
        """Check if user has specific permission"""
        user = self.users.get(username)
        if not user:
            return False
            
        # Check expiry
        if user.get("expiry") and datetime.fromisoformat(user["expiry"]) < datetime.utcnow():
            return False
            
        # Check global permissions
        if permission in user["permissions"]:
            return True
            
        # Check device-specific permissions
        if device_id and device_id in user["devices"]:
            return permission in user["devices"][device_id]["permissions"]
            
        return False

    def remove_user(self, username: str, removed_by: str) -> bool:
        """Remove a user"""
        if username not in self.users:
            return False
            
        remover = self.users.get(removed_by)
        if not remover or remover["role"] != UserRole.OWNER.value:
            return False
            
        del self.users[username]
        self._save_users()
        return True

    def update_password(self, username: str, old_password: str, 
                       new_password: str) -> bool:
        """Update user password"""
        if not self.authenticate(username, old_password):
            return False
            
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(new_password.encode(), salt)
        self.users[username]["password"] = hashed.decode()
        self._save_users()
        return True