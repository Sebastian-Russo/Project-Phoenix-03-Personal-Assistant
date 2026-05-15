def authenticate(self) -> bool:
    try:
        self._creds   = get_credentials()           # ← replaces all auth logic
        self._service = build("calendar", "v3", credentials=self._creds)
        return True
    except Exception as e:
        print(f"[gcal] Authentication failed: {e}")
        return False
