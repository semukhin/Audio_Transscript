import os
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

# Настройка путей
MODEL_NAME = "antony66/whisper-large-v3-russian"
CACHE_DIR = "./models"

def download_model():
    print(f"Загрузка модели {MODEL_NAME}...")
    
    # Создаем директорию, если она не существует
    os.makedirs(CACHE_DIR, exist_ok=True)
    
    try:
        # Загружаем модель
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            MODEL_NAME,
            torch_dtype="auto",
            low_cpu_mem_usage=True,
            use_safetensors=True,
            cache_dir=CACHE_DIR
        )
        
        # Загружаем процессор
        processor = AutoProcessor.from_pretrained(
            MODEL_NAME,
            cache_dir=CACHE_DIR
        )
        
        print("Модель успешно загружена и сохранена локально")
        
    except Exception as e:
        print(f"Ошибка при загрузке модели: {str(e)}")

if __name__ == "__main__":
    download_model() 