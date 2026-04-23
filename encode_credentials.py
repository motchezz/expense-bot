"""
Run this ONCE on your PC to get the base64 string for Railway.

Usage:
    python encode_credentials.py

Then copy the printed string into Railway as GOOGLE_CREDENTIALS_JSON
"""
import base64, pathlib

path = pathlib.Path("credentials.json")
if not path.exists():
    print("ERROR: credentials.json not found in this folder.")
else:
    encoded = base64.b64encode(path.read_bytes()).decode()
    print("\n✅ Copy everything below this line into Railway as GOOGLE_CREDENTIALS_JSON:\n")
    print(encoded)
    print("\n")
