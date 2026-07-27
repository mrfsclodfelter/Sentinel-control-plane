from datetime import datetime

LOGS = []

def log(message: str):
    LOGS.insert(0, f"{datetime.now().strftime('%H:%M:%S')}  {message}")
    del LOGS[150:]

def get_logs():
    return LOGS
