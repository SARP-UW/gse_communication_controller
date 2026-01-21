from typing import List
from datetime import datetime
from pathlib import Path

# Path to project root directory (for use in relative paths)
LOGGER_PROJECT_DIR_PATH = str(Path(__file__).parent.parent)

# Relative path keyword
LOGGER_RELATIVE_PATH_KEYWORD = "__rel__"

class Logger:
    """
    Class for logging data to a file with timestamps.
    """
    
    def __init__(self, path: str, col: List[str]) -> None:
        """
        Initializes a Logger object with the given parameters.
        
        Args:
            path: The path of the file where data will be logged.
            col: List of column names for the logged data.
        """
        if len(col) == 0:
            raise ValueError("Logger must have at least one column")
        
        # Replace relative path keyword with actual project directory path if present (start of string only!)
        full_path = path
        if path.startswith(LOGGER_RELATIVE_PATH_KEYWORD):
            full_path = LOGGER_PROJECT_DIR_PATH + path[len(LOGGER_RELATIVE_PATH_KEYWORD):]
            
        self._path: str = full_path
        self._col: List[str] = col
        
        # Write CSV header only if matching one does not already exist at top of file
        try:
            with open(self._path, 'r') as file:
                first_line = file.readline().strip()
                expected_header = "timestamp, " + ", ".join(col)
                if first_line != expected_header:
                    with open(self._path, 'a') as file:
                        file.write(expected_header + "\n")
        except FileNotFoundError:
            with open(self._path, 'w') as file:
                file.write("timestamp, " + ", ".join(col) + "\n")
        
    def __str__(self) -> str:
        """
        Gets string representation of Logger.
        """
        return f"Logger(path = {self._path}, col = {self._col})"    
    
    @property
    def path(self) -> str:
        """
        Path of file where data is logged.
        """
        return self._path
        
    @property
    def col(self) -> List[str]:
        """
        List of column names for the logged data.
        """
        return list(self._col)

    def log_data(self, data: List[str]) -> None:
        """
        Logs the provided data to the Logger's file with an added timestamp using 
        the format: "YYYY-MM-DDTHH:MM:SS.ssssss, data".
        
        Args:
            data: List of data to be logged
        """
        if len(data) != len(self._col):
            raise ValueError(f"Number of data points: {len(data)} does not match number of columns: {len(self._col)}")
        timestamp = datetime.now().isoformat()
        with open(self._path, 'a') as file:
            file.write(f"{timestamp}, {', '.join(data)}\n")
