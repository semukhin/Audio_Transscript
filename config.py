import os

class Config:
    # Основные настройки приложения
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.environ.get('SECRET_KEY') or '______________'
    
    # Настройки загрузки файлов
    UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 МБ
    
    # Настройки сессий
    SESSION_EXPIRY = 24 * 60 * 60  # 24 часа в секундах
    
    # Настройки языка по умолчанию
    DEFAULT_LANGUAGE = 'ru-RU'
    
    # Настройки для Whisper
    WHISPER_MODEL_NAME = os.environ.get('WHISPER_MODEL_NAME', 'antony66/whisper-large-v3-russian')
    WHISPER_SERVICE_URL = os.environ.get('WHISPER_SERVICE_URL', 'http://whisper:5001')

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    # Дополнительные настройки для production
    DEBUG = False
    
    # В production используйте переменные окружения
    SECRET_KEY = os.environ.get('SECRET_KEY')
    

# Выбор конфигурации в зависимости от окружения
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}