from .deepseek import DeepSeekProvider


def create_provider(settings, session):
    # Other providers implement the same complete(messages) protocol.
    return DeepSeekProvider(settings, session)
