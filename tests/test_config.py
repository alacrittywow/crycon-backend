import os

import pytest

from crycon.config import load_settings


def test_environment_wins_file_and_never_mutates_process(tmp_path):
    env = tmp_path / '.env'
    env.write_text('SUPABASE_KEY=file-placeholder\nSLEEP_MIN=1.5\nKEYWORDS=a| b,c\n')
    before = dict(os.environ)
    settings = load_settings(env, environ={'SUPABASE_KEY': 'process-placeholder'})
    assert settings.require('SUPABASE_KEY') == 'process-placeholder'
    assert settings.number('SLEEP_MIN', 1) == 1.5
    assert settings.list('KEYWORDS', []) == ['a', 'b', 'c']
    assert 'placeholder' not in repr(settings)
    assert dict(os.environ) == before


def test_dotenv_quotes_comments_literal_dollars_and_blank_defaults(tmp_path):
    env = tmp_path / '.env'
    env.write_text('GITHUB_TOKEN="literal-${HOME}" # comment\nMAX_RESULTS=\n')
    settings = load_settings(env, environ={})
    assert settings.text('GITHUB_TOKEN') == 'literal-${HOME}'
    assert settings.integer('MAX_RESULTS', 50) == 50
    assert settings.integer('MISSING', 3) == 3
    assert settings.number('MISSING', 2.0) == 2.0
    assert settings.list('MISSING', ['github']) == ['github']


def test_env_file_override_and_disable(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('SUPABASE_KEY=file-placeholder\n')
    monkeypatch.chdir(tmp_path)
    assert load_settings(environ={'CRYCON_ENV_FILE': str(env)}).text('SUPABASE_KEY') == 'file-placeholder'
    assert load_settings(environ={'CRYCON_ENV_FILE': ''}).text('SUPABASE_KEY') == ''
    assert load_settings(tmp_path / 'missing', environ={}).text('SUPABASE_KEY') == ''


def test_validation_names_only_and_is_lazy():
    settings = load_settings('', environ={'MAX_RESULTS': 'sensitive-placeholder'})
    with pytest.raises(ValueError, match='^MAX_RESULTS must be an integer$'):
        settings.integer('MAX_RESULTS', 50)
    with pytest.raises(ValueError, match='^MAX_RESULTS must be a number$'):
        settings.number('MAX_RESULTS', 50)
    with pytest.raises(RuntimeError, match='SUPABASE_URL is required'):
        settings.require('SUPABASE_URL')
    with pytest.raises(TypeError):
        settings.values['MAX_RESULTS'] = '1'


def test_blank_process_value_does_not_fall_back_to_file_secret(tmp_path):
    env = tmp_path / '.env'
    env.write_text('GITHUB_TOKEN=file-placeholder\n')
    assert load_settings(env, environ={'GITHUB_TOKEN': ''}).text('GITHUB_TOKEN') == ''
