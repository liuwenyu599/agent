from abc import ABC, abstractmethod
from typing import List, Dict
from pathlib import Path

class BaseParser(ABC):
    @abstractmethod
    def parse(self, file_path: Path) -> Dict:
        pass
    
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        pass

class ParsedDocument:
    def __init__(self):
        self.title: str = ""
        self.content: str = ""
        self.metadata: Dict = {}
        self.sections: List[Dict] = []
        self.tables: List[Dict] = []
        self.images: List[Dict] = []
