from pathlib import Path


class FileAlreadyExists(Exception):
    def __init__(self, path: Path):
        self.path = path
        self.message = f"file already exists: {path}"
        super().__init__(self.message)


class FileNotExists(Exception):
    def __init__(self, path: Path):
        self.path = path
        self.message = f"file not exists: {path}"
        super().__init__(self.message)
