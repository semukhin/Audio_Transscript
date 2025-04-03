import os
import time
import tempfile
import subprocess
import json
import logging
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline
import numpy as np
from datetime import datetime

# Настройка логгера
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация
MODEL_NAME = os.environ.get('WHISPER_MODEL_NAME', 'antony66/whisper-large-v3-russian')
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
COMPUTE_TYPE = "float16" if torch.cuda.is_available() else "float32"
CACHE_DIR = os.environ.get('WHISPER_CACHE_DIR', './models')

# Переменные для ленивой загрузки модели
model = None
processor = None
pipe = None

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
        # Создаем временный файл с уникальным именем
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            output_path = temp_file.name
        
        logger.info(f"Конвертация файла {file_path} в WAV формат...")
        
        # Конвертируем в WAV с параметрами, оптимальными для Whisper
        cmd = [
            'ffmpeg', '-y',
            '-i', file_path,
            '-vn',  # Игнорируем видеопоток
            '-ar', '16000',  # Частота дискретизации 16kHz
            '-ac', '1',      # Моно
            '-c:a', 'pcm_s16le',  # 16-bit PCM
            '-hide_banner',  # Скрываем баннер ffmpeg
            '-loglevel', 'error',  # Показываем только ошибки
            output_path
        ]
        
        # Запускаем ffmpeg
        process = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Проверяем размер выходного файла
        if os.path.getsize(output_path) == 0:
            raise Exception("Ошибка: сконвертированный файл имеет нулевой размер")
        
        if status_callback:
            status_callback(10, "Аудиофайл успешно подготовлен")
        
        logger.info(f"Аудио успешно сконвертировано в {output_path}")
        return output_path
        
    except subprocess.CalledProcessError as e:
        error_msg = f"Ошибка при конвертации аудио: {e.stderr.decode() if e.stderr else str(e)}"
        logger.error(error_msg)
        if status_callback:
            status_callback(10, error_msg)
        raise Exception(error_msg)
        
    except Exception as e:
        error_msg = f"Ошибка при подготовке аудио: {str(e)}"
        logger.error(error_msg)
        if status_callback:
            status_callback(10, error_msg)
        raise Exception(error_msg)

def load_model():
    """Ленивая загрузка модели при первом использовании"""
    global model, processor, pipe
    
    if pipe is None:
        logger.info(f"Загрузка модели {MODEL_NAME}...")
        
        try:
            # Загружаем модель и процессор
            model = AutoModelForSpeechSeq2Seq.from_pretrained(
                MODEL_NAME,
                torch_dtype=torch.float16 if COMPUTE_TYPE == "float16" else torch.float32,
                low_cpu_mem_usage=True,
                use_safetensors=True,
                cache_dir=CACHE_DIR
            )
            model.to(DEVICE)
            
            processor = AutoProcessor.from_pretrained(
                MODEL_NAME,
                cache_dir=CACHE_DIR
            )
            
            # Создаем pipeline
            pipe = pipeline(
                "automatic-speech-recognition",
                model=model,
                tokenizer=processor.tokenizer,
                feature_extractor=processor.feature_extractor,
                chunk_length_s=30,
                batch_size=16,
                torch_dtype=torch.float16 if COMPUTE_TYPE == "float16" else torch.float32,
                device=DEVICE,
                generate_kwargs={
                    "max_new_tokens": 128,
                    "language": "ru",
                    "task": "transcribe",
                    "return_timestamps": True
                }
            )
            
            logger.info(f"Модель {MODEL_NAME} успешно загружена на устройство {DEVICE} с типом {COMPUTE_TYPE}")
        except Exception as e:
            logger.error(f"Ошибка при загрузке модели: {e}")
            raise RuntimeError(f"Не удалось загрузить модель: {str(e)}")
    
    return pipe

def detect_speakers(segments, min_pause=1.0):
    """
    Простая система определения говорящих на основе пауз
    
    Args:
        segments: сегменты с временными метками
        min_pause: минимальная пауза для определения смены говорящего (в секундах)
        
    Returns:
        Список с идентификаторами говорящих для каждого сегмента
    """
    speakers = []
    current_speaker = 1
    last_end_time = 0
    
    for segment in segments:
        start_time = segment['start']
        
        # Если пауза превышает порог, считаем, что говорит другой человек
        if start_time - last_end_time > min_pause:
            current_speaker = 2 if current_speaker == 1 else 1
        
        speakers.append(current_speaker)
        last_end_time = segment['end']
    
    return speakers

def transcribe_with_whisper(file_path, language_code=None, enable_timestamps=False, status_callback=None):
    """Транскрибирование с использованием модели whisper-large-v3-russian"""
    try:
        if status_callback:
            status_callback(15, f"Запуск транскрипции с {MODEL_NAME}")
        
        # Подготовка аудиофайла
        prepared_file = prepare_audio(file_path, status_callback)
        
        # Загрузка модели (ленивая загрузка)
        if status_callback:
            status_callback(20, "Загрузка модели...")
        
        try:
            asr_pipeline = load_model()
        except Exception as e:
            logger.error(f"Ошибка при загрузке модели: {e}")
            if status_callback:
                status_callback(25, f"Ошибка при загрузке модели: {str(e)}")
            return f"Ошибка при загрузке модели: {str(e)}"
        
        # Запуск транскрипции
        if status_callback:
            status_callback(30, "Начало распознавания речи...")
        
        start_time = time.time()
        
        # Определяем параметры для распознавания
        transcribe_params = {
            "return_timestamps": True,  # Всегда получаем таймкоды для внутренней обработки
        }
        
        # Если указан язык и это не русский, явно задаем языковой код
        if language_code and language_code.lower() not in ["ru", "ru-ru"]:
            # Конвертируем коды языков из формата Google в формат Whisper
            lang_map = {
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
            whisper_lang = lang_map.get(language_code, language_code[:2].lower())
            transcribe_params["language"] = whisper_lang
            logger.info(f"Используем язык: {whisper_lang}")
        
        # Функция обратного вызова для отслеживания прогресса
        def progress_callback(step, total_steps):
            if status_callback:
                progress = 30 + int((step / total_steps) * 60)
                status_callback(progress, f"Распознавание: {int((step / total_steps) * 100)}%")
        
        # Добавляем обратный вызов для отслеживания прогресса
        transcribe_params["callback_function"] = progress_callback
        
        # Проверка существования файла
        if not os.path.exists(prepared_file):
            error_msg = f"Ошибка: файл не существует: {prepared_file}"
            logger.error(error_msg)
            if status_callback:
                status_callback(30, error_msg)
            return error_msg
        
        # Проверка размера файла
        try:
            file_size = os.path.getsize(prepared_file)
            if file_size == 0:
                error_msg = "Ошибка: файл имеет нулевой размер"
                logger.error(error_msg)
                if status_callback:
                    status_callback(30, error_msg)
                return error_msg
            logger.info(f"Размер файла для транскрипции: {file_size} байт")
        except Exception as e:
            logger.warning(f"Ошибка при проверке размера файла: {e}")
        
        # Выполняем распознавание
        try:
            result = asr_pipeline(
                prepared_file,
                return_timestamps=True,
                generate_kwargs={
                    "language": language_code[:2].lower() if language_code else "ru",
                    "task": "transcribe"
                }
            )
            
            # Отладочный вывод
            logger.info(f"Тип результата: {type(result)}")
            logger.info(f"Структура результата: {result}")
            
            # Обработка результатов
            if enable_timestamps:
                # Если результат - это строка или словарь без чанков, возвращаем базовый формат
                if isinstance(result, str) or (isinstance(result, dict) and not result.get('chunks')):
                    return [{
                        'speaker': "Говорящий 1",
                        'text': result if isinstance(result, str) else result.get('text', ''),
                        'start_time': "00:00"
                    }]
                
                # Получаем чанки из результата
                chunks = []
                if isinstance(result, dict):
                    if 'chunks' in result:
                        chunks = result['chunks']
                    elif 'text' in result:
                        chunks = [{'text': result['text'], 'timestamp': [0, 0]}]
                
                # Преобразуем временные метки в нужный формат
                segments = []
                for chunk in chunks:
                    if isinstance(chunk, dict):
                        timestamp = chunk.get('timestamp', [0, 0])
                        if isinstance(timestamp, (list, tuple)) and len(timestamp) >= 2:
                            segments.append({
                                'text': chunk.get('text', '').strip(),
                                'start': timestamp[0],
                                'end': timestamp[1]
                            })
                
                # Если нет сегментов после обработки, возвращаем базовый формат
                if not segments:
                    return [{
                        'speaker': "Говорящий 1",
                        'text': str(result),
                        'start_time': "00:00"
                    }]
                
                # Определяем говорящих
                speaker_ids = detect_speakers(segments)
                
                # Форматируем транскрипцию
                transcript = []
                for i, segment in enumerate(segments):
                    speaker_id = speaker_ids[i]
                    transcript.append({
                        'speaker': f"Говорящий {speaker_id}",
                        'text': segment['text'].strip(),
                        'start_time': format_time(segment['start'])
                    })
                
                return transcript
            else:
                # Просто текст без таймкодов
                if isinstance(result, dict):
                    return result.get('text', '')
                return str(result)
                
        except Exception as e:
            logger.error(f"Ошибка при распознавании: {e}")
            logger.exception("Подробности ошибки:")  # Добавляем полный стек ошибки
            if status_callback:
                status_callback(60, f"Ошибка при распознавании: {str(e)}")
            return f"Ошибка при распознавании: {str(e)}"
        
    except Exception as e:
        logger.error(f"Ошибка при распознавании аудио с {MODEL_NAME}: {e}")
        import traceback
        traceback.print_exc()
        if status_callback:
            status_callback(90, f"Ошибка: {str(e)}")
        return f"Ошибка при транскрибировании: {str(e)}"
    finally:
        # Удаляем временные файлы
        if 'prepared_file' in locals() and prepared_file != file_path:
            try:
                if os.path.exists(prepared_file):
                    os.remove(prepared_file)
                    logger.info(f"Удален временный файл: {prepared_file}")
            except Exception as e:
                logger.error(f"Ошибка при удалении временного файла: {e}")