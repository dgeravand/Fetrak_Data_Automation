# ------------------------------------------------------------------------------
# UTILS
# ------------------------------------------------------------------------------
# Utility functions for environment variable retrieval.
# ------------------------------------------------------------------------------
from dotenv import load_dotenv
import os

load_dotenv()


def env(key):
    val = os.getenv(key)
    if val is None:
        raise Exception(f"Missing env: {key}")
    return val
