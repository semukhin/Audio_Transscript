import os

class Config:
    # Основные настройки приложения
    DEBUG = False
    TESTING = False
    SECRET_KEY = os.environ.get('SECRET_KEY') or '______________'
    
    # Настройки загрузки файлов
    UPLOAD_FOLDER = 'uploads'
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 МБ
    
    # Путь к учетным данным Google Cloud
    CREDENTIALS_PATH = '/home/semukhin/Documents/GitHub/Audio_Transscript/lawgpt2025-4a4960627584.json'

    # Настройки сессий
    SESSION_EXPIRY = 24 * 60 * 60  # 24 часа в секундах
    
    # Настройки Google Cloud Storage
    GCS_BUCKET_NAME = 'audio_transscript'
    
    # Настройки языка по умолчанию
    DEFAULT_LANGUAGE = 'ru-RU'
    
    # Настройки для Vertex AI
    VERTEX_AI_PROJECT = 'lawgpt2025'
    VERTEX_AI_LOCATION = 'us-central1'

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    # Дополнительные настройки для production
    DEBUG = False
    
    # В production используйте переменные окружения
    SECRET_KEY = os.environ.get('SECRET_KEY')
    CREDENTIALS_PATH = os.environ.get('GOOGLE_CREDENTIALS_PATH')
    
    # Настройки HTTPS
    SSL_CERTIFICATE = os.environ.get('SSL_CERTIFICATE')
    SSL_KEY = os.environ.get('SSL_KEY')

# Выбор конфигурации в зависимости от окружения
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

