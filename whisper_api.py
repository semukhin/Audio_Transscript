import os
import tempfile
import time
import json
import logging
import shutil
import whisper
from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel
import subprocess

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Whisper Transcription API")

# Инициализация переменных
MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "small")
MODEL_DIR = os.environ.get("WHISPER_MODEL_DIR", "/app/models")
ACTIVE_TASKS = {}

# Загрузка модели при запуске (можно закомментировать если нежелательно при старте)
# Будет загружаться при первом запросе
logger.info(f"Предварительная загрузка модели Whisper {MODEL_SIZE}...")
try:
    model = whisper.load_model(MODEL_SIZE, download_root=MODEL_DIR)
    logger.info(f"Модель Whisper {MODEL_SIZE} успешно загружена")
except Exception as e:
    logger.error(f"Ошибка при предзагрузке модели: {e}")
    model = None

class TranscriptionStatus(BaseModel):
    task_id: str
    status: str
    progress: float = 0
    message: str = ""
    result: Optional[dict] = None

def format_time(seconds):
    """Форматирование времени в формат ММ:СС"""
    minutes = int(seconds) // 60
    seconds = int(seconds) % 60
    return f"{minutes:02d}:{seconds:02d}"

def prepare_audio(file_path):
    """Подготовка аудиофайла для транскрипции"""
    try:
        output_path = file_path + '.converted.wav'
        # Конвертируем в WAV с параметрами, оптимальными для Whisper
        cmd = [
            'ffmpeg', '-y', '-i', file_path, 
            '-ar', '16000', '-ac', '1', 
            '-c:a', 'pcm_s16le', output_path
        ]
        
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return output_path
    except Exception as e:
        logger.error(f"Ошибка при подготовке аудио: {e}")
        return file_path

def transcribe_task(task_id: str, file_path: str, language: Optional[str] = None, timestamps: bool = False):
    """Фоновая задача для транскрипции"""
    try:
        ACTIVE_TASKS[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "Подготовка к транскрипции"
        }
        
        # Загрузка модели, если еще не загружена
        global model
        if model is None:
            ACTIVE_TASKS[task_id]["message"] = f"Загрузка модели Whisper {MODEL_SIZE}..."
            model = whisper.load_model(MODEL_SIZE, download_root=MODEL_DIR)
        
        # Подготовка аудиофайла
        ACTIVE_TASKS[task_id]["progress"] = 10
        ACTIVE_TASKS[task_id]["message"] = "Подготовка аудиофайла..."
        prepared_file = prepare_audio(file_path)
        
        # Настройка параметров транскрипции
        ACTIVE_TASKS[task_id]["progress"] = 20
        ACTIVE_TASKS[task_id]["message"] = "Транскрипция аудио..."
        
        transcribe_options = {
            "task": "transcribe",
            "verbose": True
        }
        
        if language:
            transcribe_options["language"] = language
        
        if timestamps:
            transcribe_options["word_timestamps"] = True
        
        # Запуск транскрипции
        start_time = time.time()
        result = model.transcribe(prepared_file, **transcribe_options)
        elapsed_time = time.time() - start_time
        
        ACTIVE_TASKS[task_id]["progress"] = 90
        ACTIVE_TASKS[task_id]["message"] = f"Обработка результатов (заняло {elapsed_time:.1f} сек)"
        
        # Форматирование результатов
        if timestamps:
            # Форматирование с таймингами и сегментами
            formatted_result = []
            last_speaker_id = 1
            previous_end = 0
            
            for i, segment in enumerate(result["segments"]):
                start = segment.get("start", 0)
                
                # Определяем говорящего по паузам
                if start - previous_end > 1.5:
                    last_speaker_id = 2 if last_speaker_id == 1 else 1
                
                previous_end = segment.get("end", 0)
                
                formatted_result.append({
                    "speaker": f"Говорящий {last_speaker_id}",
                    "text": segment.get("text", "").strip(),
                    "start_time": format_time(start)
                })
            
            ACTIVE_TASKS[task_id]["result"] = formatted_result
        else:
            # Просто текст
            ACTIVE_TASKS[task_id]["result"] = result["text"].strip()
        
        # Завершение задачи
        ACTIVE_TASKS[task_id]["status"] = "completed"
        ACTIVE_TASKS[task_id]["progress"] = 100
        ACTIVE_TASKS[task_id]["message"] = "Транскрипция завершена"
        
        # Удаление временных файлов
        try:
            if prepared_file != file_path and os.path.exists(prepared_file):
                os.remove(prepared_file)
            os.remove(file_path)
        except Exception as e:
            logger.error(f"Ошибка при удалении временных файлов: {e}")
        
    except Exception as e:
        logger.error(f"Ошибка при транскрипции: {e}")
        ACTIVE_TASKS[task_id]["status"] = "error"
        ACTIVE_TASKS[task_id]["message"] = f"Ошибка: {str(e)}"

@app.post("/transcribe")
async def transcribe_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    timestamps: bool = Form(False)
):
    """Эндпоинт для транскрипции аудиофайла"""
    try:
        # Создаем временный файл для сохранения загруженного аудио
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            # Копируем содержимое загруженного файла во временный файл
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name
        
        # Генерируем ID задачи
        task_id = f"task_{int(time.time())}_{os.urandom(4).hex()}"
        
        # Запускаем фоновую задачу для транскрипции
        background_tasks.add_task(transcribe_task, task_id, temp_path, language, timestamps)
        
        return JSONResponse({
            "task_id": task_id,
            "message": "Задача транскрипции запущена"
        })
    
    except Exception as e:
        logger.error(f"Ошибка при обработке запроса: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Ошибка при обработке файла: {str(e)}"}
        )

@app.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """Проверка статуса задачи по ID"""
    if task_id not in ACTIVE_TASKS:
        return JSONResponse(
            status_code=404,
            content={"error": "Задача не найдена"}
        )
    
    task_info = ACTIVE_TASKS[task_id]
    
    # Возвращаем результат, если задача завершена
    if task_info["status"] == "completed":
        result = task_info.pop("result", None)
        
        return JSONResponse({
            "status": task_info["status"],
            "progress": task_info["progress"],
            "message": task_info["message"],
            "result": result
        })
    
    # Для незавершенных задач возвращаем только статус
    return JSONResponse({
        "status": task_info["status"],
        "progress": task_info["progress"],
        "message": task_info["message"]
    })

@app.get("/health")
async def health_check():
    """Проверка работоспособности сервиса"""
    return {"status": "healthy", "model": MODEL_SIZE}