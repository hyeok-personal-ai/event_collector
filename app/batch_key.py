"""Public runner credentials are supplied only through its environment."""
import os

def read_key():
    value = os.environ.get('RADAR_BATCH_KEY')
    if not value or len(value) < 32:
        raise RuntimeError('Configure RADAR_BATCH_KEY in GitHub Actions secrets')
    return value
