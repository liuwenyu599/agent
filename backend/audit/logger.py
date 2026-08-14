import json
from datetime import datetime
from typing import Dict, Optional

from backend.config.settings import LOG_DIR

class AuditLogger:
    def __init__(self):
        self.log_file = LOG_DIR / f"audit_{datetime.now().strftime('%Y%m')}.jsonl"
    
    def log(self, user_id: str, action: str, resource_type: str = None, resource_id: str = None, detail: Dict = None, ip_address: str = None):
        entry = {
            "time": datetime.now().isoformat(),
            "user_id": user_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "detail": detail or {},
            "ip_address": ip_address
        }
        
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
