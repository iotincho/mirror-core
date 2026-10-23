"""Compatibility constructor; audio workflow dependencies are composed in bootstrap."""


def ProcessAudioNote(runtime_factory, provider_factory):
    from src.bootstrap.audio import build_audio_processor

    return build_audio_processor(runtime_factory, provider_factory)
