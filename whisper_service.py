import os
import time
import tempfile
import subprocess
import json
import logging
from datetime import datetime

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Путь к директории с моделями Whisper
WHISPER_MODEL_DIR = os.environ.get('WHISPER_MODEL_DIR', '/app/models')

# Размер модели Whisper: tiny, base, small, medium или large
WHISPER_MODEL_SIZE = os.environ.get('WHISPER_MODEL_SIZE', 'small')

def format_time(seconds):
    """Форматирование времени в формат ММ:СС"""
    minutes = int(seconds) // 60
    seconds = int(seconds) % 60
    return f"{minutes:02d}:{seconds:02d}"

def prepare_audio(file_path, status_callback=None):
    """Подготовка аудиофайла для транскрипции"""
    if status_callback:
        status_callback(5, "Подготовка аудиофайла...")
    
    try:
        output_path = file_path + '.converted.wav'
        # Конвертируем в WAV с параметрами, оптимальными для Whisper
        cmd = [
            'ffmpeg', '-y', '-i', file_path, 
            '-ar', '16000', '-ac', '1', 
            '-c:a', 'pcm_s16le', output_path
        ]
        
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        if status_callback:
            status_callback(10, "Аудиофайл успешно подготовлен")
        
        return output_path
    except Exception as e:
        logger.error(f"Ошибка при подготовке аудио: {e}")
        if status_callback:
            status_callback(10, f"Ошибка при подготовке аудио: {str(e)}")
        return file_path

def transcribe_with_whisper(file_path, language_code=None, enable_timestamps=False, status_callback=None):
    """Транскрибирование с использованием локальной модели Whisper"""
    try:
        if status_callback:
            status_callback(15, f"Запуск транскрипции с Whisper (модель: {WHISPER_MODEL_SIZE})")
        
        # Подготовка аудиофайла
        prepared_file = prepare_audio(file_path, status_callback)
        
        # Определяем язык для Whisper
        whisper_lang = None
        if language_code:
            # Преобразование кодов языка из формата Google в формат Whisper
            lang_map = {
                'ru-RU': 'ru', 
                'en-US': 'en', 
                'uk-UA': 'uk', 
                'be-BY': 'be', 
                'kk-KZ': 'kk', 
                'de-DE': 'de', 
                'fr-FR': 'fr', 
                'es-ES': 'es', 
                'it-IT': 'it', 
                'zh-CN': 'zh', 
                'ja-JP': 'ja'
            }
            whisper_lang = lang_map.get(language_code)
        
        # Создаем временный файл для сохранения результатов
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as tmp_file:
            output_json = tmp_file.name
        
        # Формируем команду для запуска Whisper
        cmd = [
            'whisper', prepared_file,
            '--model', WHISPER_MODEL_SIZE,
            '--output_dir', tempfile.gettempdir(),
            '--output_format', 'json'
        ]
        
        # Добавляем параметр языка, если указан
        if whisper_lang:
            cmd.extend(['--language', whisper_lang])
        
        # Параметры для таймингов
        if enable_timestamps:
            cmd.append('--word_timestamps')
        
        if status_callback:
            status_callback(20, "Запуск процесса распознавания...")
        
        # Запускаем Whisper
        start_time = time.time()
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Отслеживаем прогресс
        for line in process.stderr:
            if 'progress' in line.lower():
                try:
                    progress_str = line.strip().split('progress: ')[1].split('%')[0]
                    progress = float(progress_str)
                    # Масштабируем прогресс от 20% до 90%
                    scaled_progress = 20 + (progress * 0.7)
                    if status_callback:
                        status_callback(int(scaled_progress), f"Распознавание: {progress:.1f}%")
                except (IndexError, ValueError):
                    pass
        
        # Ждем завершения процесса
        process.wait()
        elapsed_time = time.time() - start_time
        
        if process.returncode != 0:
            error_output = process.stderr.read()
            logger.error(f"Ошибка Whisper: {error_output}")
            if status_callback:
                status_callback(90, f"Ошибка при транскрибировании: код {process.returncode}")
            return "Ошибка при транскрибировании аудио"
        
        # Определяем путь к сгенерированному JSON-файлу
        base_name = os.path.basename(prepared_file).rsplit('.', 2)[0]
        json_file = os.path.join(tempfile.gettempdir(), f"{base_name}.json")
        
        if status_callback:
            status_callback(90, f"Транскрипция завершена за {elapsed_time:.1f} секунд")
        
        # Обработка результатов
        with open(json_file, 'r', encoding='utf-8') as f:
            result = json.load(f)
        
        # Форматирование вывода
        if enable_timestamps:
            # Результат с таймингами и разделением по говорящим
            segments = result.get('segments', [])
            transcript = []
            
            # Определение говорящих (Whisper не делает диаризацию, определим по переменам)
            last_speaker_id = 1
            previous_end = 0
            
            for i, segment in enumerate(segments):
                start = segment.get('start', 0)
                
                # Если разрыв больше 1.5 секунд, считаем новым говорящим
                if start - previous_end > 1.5:
                    last_speaker_id = 2 if last_speaker_id == 1 else 1
                
                previous_end = segment.get('end', 0)
                
                transcript.append({
                    'speaker': f"Говорящий {last_speaker_id}",
                    'text': segment.get('text', '').strip(),
                    'start_time': format_time(start)
                })
            
            return transcript
        else:
            # Просто текст без таймингов
            return result.get('text', '').strip()
        
    except Exception as e:
        logger.error(f"Ошибка при распознавании аудио с Whisper: {e}")
        if status_callback:
            status_callback(90, f"Ошибка: {str(e)}")
        return f"Ошибка при транскрибировании: {str(e)}"
    finally:
        # Удаляем временные файлы
        if 'prepared_file' in locals() and prepared_file != file_path:
            try:
                os.remove(prepared_file)
            except:
                pass