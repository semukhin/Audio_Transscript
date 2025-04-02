import os
import tempfile
import time
import json
import logging
import shutil
from fastapi import FastAPI, File, UploadFile, Form, BackgroundTasks
from fastapi.responses import JSONResponse
from typing import Optional
from pydantic import BaseModel

# Импортируем обновленный сервис
from whisper_service import transcribe_with_whisper, format_time

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Whisper Russian Transcription API")

# Инициализация переменных
MODEL_NAME = os.environ.get("WHISPER_MODEL_NAME", "antony66/whisper-large-v3-russian")
ACTIVE_TASKS = {}

class TranscriptionStatus(BaseModel):
    task_id: str
    status: str
    progress: float = 0
    message: str = ""
    result: Optional[dict] = None

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
        
        # Удаление временных файлов
        try:
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
    return {"status": "healthy", "model": MODEL_NAME}