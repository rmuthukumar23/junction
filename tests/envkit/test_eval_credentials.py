"""Credential forwarding for model runs: the key reaches OpenCode, its value never reaches argv."""
from argparse import Namespace

from envkit.evalrun import credential_env_name, credential_forwarding


def ns(model, agent="opencode", credential_env=None):
    return Namespace(model=model, agent=agent, credential_env=credential_env)


def test_google_model_forwards_template_not_value():
    a = ns("google/gemini-4-hydrogen")
    assert credential_env_name(a) == "GEMINI_API_KEY"
    assert credential_forwarding(a) == ["--ae", "GOOGLE_GENERATIVE_AI_API_KEY=${GEMINI_API_KEY}"]


def test_custom_credential_variable_is_used():
    a = ns("gemini/gemini-4-hydrogen", credential_env="MY_KEY")
    assert credential_forwarding(a) == ["--ae", "GOOGLE_GENERATIVE_AI_API_KEY=${MY_KEY}"]


def test_anthropic_and_openai_models_use_their_own_keys():
    a = ns("anthropic/claude-opus-5-5")
    assert credential_env_name(a) == "ANTHROPIC_API_KEY"
    assert credential_forwarding(a) == ["--ae", "ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}"]
    a = ns("openai/gpt-5")
    assert credential_env_name(a) == "OPENAI_API_KEY"
    assert credential_forwarding(a) == ["--ae", "OPENAI_API_KEY=${OPENAI_API_KEY}"]


def test_unknown_provider_keeps_openai_default_and_forwards_nothing():
    a = ns("someprovider/model")
    assert credential_env_name(a) == "OPENAI_API_KEY"
    assert credential_forwarding(a) == []
