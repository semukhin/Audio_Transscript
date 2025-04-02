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
CACHE_DIR = os.environ.get('WHISPER_CACHE_DIR', '/app/models')

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

def load_model():
    """Ленивая загрузка модели при первом использовании"""
    global model, processor, pipe
    
    if pipe is None:
        logger.info(f"Загрузка модели {MODEL_NAME}...")
        
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
            max_new_tokens=128,
            chunk_length_s=30,
            batch_size=16,
            return_timestamps=True,
            torch_dtype=torch.float16 if COMPUTE_TYPE == "float16" else torch.float32,
            device=DEVICE,
        )
        
        logger.info(f"Модель {MODEL_NAME} успешно загружена на устройство {DEVICE} с типом {COMPUTE_TYPE}")
    
    return pipe

def detect_speakers(segments, min_pause=1.0):
    """
    Простая система определения говорящих на основе пауз
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
        
        asr_pipeline = load_model()
        
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
        
        # Отслеживание прогресса на основе размера файла
        file_size = os.path.getsize(prepared_file)
        
        def progress_callback(step, total_steps):
            if status_callback:
                progress = 30 + int((step / total_steps) * 60)
                status_callback(progress, f"Распознавание: {int((step / total_steps) * 100)}%")
        
        # Добавляем обратный вызов для отслеживания прогресса
        transcribe_params["callback_function"] = progress_callback
        
        # Выполняем распознавание
        result = asr_pipeline(
            prepared_file,
            generate_kwargs={"language": "ru"},
            **transcribe_params
        )
        
        elapsed_time = time.time() - start_time
        
        if status_callback:
            status_callback(90, f"Транскрипция завершена за {elapsed_time:.1f} секунд")
        
        # Обработка результатов
        if enable_timestamps:
            # Обработка результатов с таймкодами
            segments = result.get("chunks", [])
            
            if not segments and "segments" in result:
                segments = result["segments"]
            
            # Если есть сегменты, обрабатываем их
            if segments:
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
                # Если сегменты не найдены, возвращаем весь текст с начальным таймкодом
                return [{
                    'speaker': "Говорящий 1",
                    'text': result.get('text', '').strip(),
                    'start_time': "00:00"
                }]
        else:
            # Просто текст без таймкодов
            return result.get('text', '').strip()
        
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
                os.remove(prepared_file)
            except Exception as e:
                logger.error(f"Ошибка при удалении временного файла: {e}")