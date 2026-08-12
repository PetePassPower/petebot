class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self):
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _FakeResponse("fake reply")


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeClient:
    def __init__(self):
        self.chat = _FakeChat()


def test_chat_completion_builds_messages_and_returns_content():
    from petebot.llm import chat_completion, DEFAULT_MODEL

    client = _FakeClient()
    history = [
        {"role": "user", "content": "안녕"},
        {"role": "assistant", "content": "안녕하세요"},
    ]

    result = chat_completion(client, "SYSTEM_PROMPT", history, "질문입니다", model=DEFAULT_MODEL)

    assert result == "fake reply"
    sent = client.chat.completions.last_kwargs
    assert sent["model"] == DEFAULT_MODEL
    assert sent["messages"][0] == {"role": "system", "content": "SYSTEM_PROMPT"}
    assert sent["messages"][1:3] == history
    assert sent["messages"][3] == {"role": "user", "content": "질문입니다"}
