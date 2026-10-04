class Session:
    def __init__(self, token=None):
        self.token = token

    def __bool__(self):
        return bool(self.token)

    def __repr__(self):
        state = self.token or "anonymous"
        return f"<Session {state}>"
