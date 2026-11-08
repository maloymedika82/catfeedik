import pytest
from backend.server import validate


def valid():
    return dict(APP_ENV='production',ALLOW_DEV_LOGIN='0',ALLOW_DEV_ADMIN='0',DATABASE_URL='postgresql+psycopg://test',TELEGRAM_BOT_TOKEN='123:test_only',MAX_VIDEO_BYTES='20971520')


def test_valid_server_settings():
    validate(valid())


@pytest.mark.parametrize('name,value',[('APP_ENV','development'),('ALLOW_DEV_LOGIN','1'),('ALLOW_DEV_ADMIN','1'),('DATABASE_URL','sqlite:///test'),('TELEGRAM_BOT_TOKEN',''),('MAX_VIDEO_BYTES','25000000'),('MAX_VIDEO_BYTES','1.5')])
def test_server_refuses_invalid_settings_without_exposing_values(name,value):
    settings=valid();settings[name]=value
    with pytest.raises(ValueError) as error:validate(settings)
    assert name in str(error.value)
    if settings['TELEGRAM_BOT_TOKEN']:assert settings['TELEGRAM_BOT_TOKEN'] not in str(error.value)
