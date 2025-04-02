import os
import time
import requests
import logging
from typing import Optional, Callable

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# URL сервиса Whisper API
WHISPER_SERVICE_URL = os.environ.get('WHISPER_SERVICE_URL', 'http://whisper:5001')

def transcribe_with_whisper_api(
    file_path: str, 
    language_code: Optional[str] = None, 
    enable_timestamps: bool = False, 
    status_callback: Optional[Callable[[int, str], None]] = None
):
    """Отправка файла на транскрипцию через Whisper API сервис с улучшенной моделью русского языка"""
    try:
        if status_callback:
            status_callback(5, "Подготовка к отправке файла на транскрипцию с улучшенной моделью для русского языка")
        
        # Подготовка данных для запроса
        with open(file_path, 'rb') as file:
            files = {'file': (os.path.basename(file_path), file)}
            
            # Подготовка параметров
            data = {'timestamps': 'true' if enable_timestamps else 'false'}
            
            # Добавляем языковой код, если указан
            if language_code:
                data['language'] = language_code
            
            if status_callback:
                status_callback(10, "Отправка файла на сервер транскрипции")
                
            # Отправляем запрос
            response = requests.post(
                f'{WHISPER_SERVICE_URL}/transcribe',
                files=files,
                data=data
            )
            
            # Проверяем ответ
            if response.status_code != 200:
                logger.error(f"Ошибка при отправке запроса: {response.text}")
                if status_callback:
                    status_callback(15, f"Ошибка сервера: {response.status_code}")
                return f"Ошибка сервера транскрипции: {response.status_code}"
            
            # Получаем ID задачи
            task_data = response.json()
            task_id = task_data.get('task_id')
            
            if not task_id:
                logger.error("Сервер не вернул ID задачи")
                if status_callback:
                    status_callback(15, "Ошибка: сервер не вернул ID задачи")
                return "Ошибка сервера транскрипции: не получен ID задачи"
            
            if status_callback:
                status_callback(20, f"Файл принят сервером, модель: {task_data.get('model', 'whisper-large-v3-russian')}")
            
            # Ожидаем завершения задачи и получаем результаты
            completed = False
            last_progress = 20
            
            while not completed:
                time.sleep(2)  # Пауза между запросами статуса
                
                status_response = requests.get(f'{WHISPER_SERVICE_URL}/status/{task_id}')
                
                if status_response.status_code != 200:
                    logger.error(f"Ошибка при проверке статуса: {status_response.text}")
                    if status_callback:
                        status_callback(last_progress, f"Ошибка при проверке статуса: {status_response.status_code}")
                    time.sleep(5)  # Увеличиваем паузу при ошибке
                    continue
                
                status_data = status_response.json()
                current_status = status_data.get('status')
                progress = status_data.get('progress', 0)
                message = status_data.get('message', '')
                
                # Масштабируем прогресс от сервера (0-100) на наш диапазон (20-90)
                scaled_progress = 20 + int(progress * 0.7)
                
                if scaled_progress > last_progress:
                    if status_callback:
                        status_callback(scaled_progress, message)
                    last_progress = scaled_progress
                
                if current_status == 'completed':
                    completed = True
                    result = status_data.get('result')
                    
                    if status_callback:
                        status_callback(95, "Транскрипция завершена, обработка результатов")
                    
                    return result
                
                elif current_status == 'error':
                    if status_callback:
                        status_callback(90, f"Ошибка: {message}")
                    return f"Ошибка при транскрибировании: {message}"
            
            return "Не удалось получить результаты транскрипции"
        
    except Exception as e:
        logger.error(f"Ошибка при взаимодействии с Whisper API: {e}")
        if status_callback:
            status_callback(90, f"Ошибка: {str(e)}")
        return f"Ошибка: {str(e)}"