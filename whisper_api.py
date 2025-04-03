import os
import tempfile
import time
import json
import logging
import shutil
import ssl
import urllib3
from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel

# Отключаем проверку SSL сертификатов
ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Импортируем обновленный сервис
from whisper_service import transcribe_with_whisper, format_time

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Whisper Russian Transcription API",
    description="API для транскрибирования аудио с использованием улучшенной русской модели Whisper",
    version="1.0.0"
)

# Добавляем CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене лучше указать конкретные домены
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализация переменных
MODEL_NAME = os.environ.get("WHISPER_MODEL_NAME", "antony66/whisper-large-v3-russian")
ACTIVE_TASKS = {}

class TranscriptionStatus(BaseModel):
    task_id: str
    status: str
    progress: float = 0
    message: str = ""
    result: Optional[dict] = None

def cleanup_temp_files(file_path: str):
    """Очистка временных файлов"""
    try:
        # Удаляем оригинальный временный файл
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Удален временный файл: {file_path}")
        
        # Удаляем конвертированный WAV файл
        wav_path = f"{file_path}.converted.wav"
        if os.path.exists(wav_path):
            os.remove(wav_path)
            logger.info(f"Удален временный WAV файл: {wav_path}")
    except Exception as e:
        logger.error(f"Ошибка при удалении временных файлов: {e}")

def transcribe_task(task_id: str, file_path: str, language: Optional[str] = None, timestamps: bool = False):
    """Фоновая задача для транскрипции"""
    try:
        ACTIVE_TASKS[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "Подготовка к транскрипции"
        }
        
        # Функция обновления статуса
        def update_status(percent, message):
            ACTIVE_TASKS[task_id] = {
                "status": "processing" if percent < 100 else "completed",
                "progress": percent,
                "message": message
            }
        
        # Запуск транскрибирования
        result = transcribe_with_whisper(
            file_path=file_path,
            language_code=language,
            enable_timestamps=timestamps,
            status_callback=update_status
        )
        
        # Обработка результатов
        ACTIVE_TASKS[task_id]["status"] = "completed"
        ACTIVE_TASKS[task_id]["progress"] = 100
        ACTIVE_TASKS[task_id]["message"] = "Транскрипция завершена"
        ACTIVE_TASKS[task_id]["result"] = result
        
    except Exception as e:
        logger.error(f"Ошибка при транскрипции: {e}")
        ACTIVE_TASKS[task_id]["status"] = "error"
        ACTIVE_TASKS[task_id]["message"] = f"Ошибка: {str(e)}"
    finally:
        # Очищаем временные файлы в любом случае
        cleanup_temp_files(file_path)

@app.post("/transcribe")
async def transcribe_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    language: Optional[str] = Form(None),
    timestamps: bool = Form(False)
):
    """Эндпоинт для транскрипции аудиофайла"""
    try:
        # Проверка размера файла (ограничение в 100 МБ)
        file_size = 0
        chunk_size = 1024 * 1024  # 1 МБ
        max_size = 100 * 1024 * 1024  # 100 МБ
        
        # Перематываем файл в начало для проверки размера
        await file.seek(0)
        
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            file_size += len(chunk)
            if file_size > max_size:
                return JSONResponse(
                    status_code=413,
                    content={"error": "Файл слишком большой (максимум 100 МБ)"}
                )
        
        # Перематываем файл в начало для последующего копирования
        await file.seek(0)
        
        # Создаем временный файл для сохранения загруженного аудио
        suffix = os.path.splitext(file.filename)[1] if file.filename else ".wav"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            # Копируем содержимое загруженного файла во временный файл
            shutil.copyfileobj(file.file, temp_file)
            temp_path = temp_file.name
        
        logger.info(f"Файл {file.filename} (размер: {file_size} байт) сохранен как {temp_path}")
        
        # Генерируем ID задачи
        task_id = f"task_{int(time.time())}_{os.urandom(4).hex()}"
        
        # Запускаем фоновую задачу для транскрипции
        background_tasks.add_task(transcribe_task, task_id, temp_path, language, timestamps)
        
        return JSONResponse({
            "task_id": task_id,
            "message": "Задача транскрипции запущена",
            "model": MODEL_NAME
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
    
    task_info = ACTIVE_TASKS[task_id].copy()
    
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
    return {
        "status": "healthy", 
        "model": MODEL_NAME,
        "device": os.environ.get("DEVICE", "cpu"),
        "timestamp": time.time()
    }

# Очистка старых задач
@app.get("/cleanup")
async def cleanup_tasks(age_hours: int = 24):
    """Очистка старых задач"""
    try:
        current_time = time.time()
        count_before = len(ACTIVE_TASKS)
        tasks_to_remove = []
        
        # Проверяем время создания каждой задачи
        for task_id, task_info in ACTIVE_TASKS.items():
            # Извлекаем время из ID задачи (формат: task_timestamp_hash)
            try:
                task_time = int(task_id.split('_')[1])
                if current_time - task_time > age_hours * 3600:
                    tasks_to_remove.append(task_id)
            except Exception:
                # Если не удалось извлечь время, пропускаем
                continue
        
        # Удаляем старые задачи
        for task_id in tasks_to_remove:
            del ACTIVE_TASKS[task_id]
        
        return {
            "status": "success",
            "tasks_before": count_before,
            "tasks_after": len(ACTIVE_TASKS),
            "tasks_removed": len(tasks_to_remove)
        }
    except Exception as e:
        logger.error(f"Ошибка при очистке задач: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"Ошибка при очистке задач: {str(e)}"}
        )