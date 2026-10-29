"""Generate a one-use SpendFlow password recovery code on the server.

Usage: python -m backend.reset_password_code
"""
from getpass import getpass
from .db import init_db, connect
from .auth import issue_password_reset

def main():
    init_db()
    email = input("Registered email: ").strip().lower()
    db = connect()
    try:
        token = issue_password_reset(db, email)
        if token is None:
            print("No matching local account found.")
            return
        print("\nOne-time reset code (valid for 15 minutes):")
        print(token)
        print("\nOpen SpendFlow > Sign in > Forgot password and enter this code.")
        print("Do not share the code or commit it to Git.")
    finally:
        db.close()

if __name__ == "__main__":
    main()
