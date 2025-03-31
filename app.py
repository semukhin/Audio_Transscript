import os
import json
import tempfile
import uuid
import time
import datetime
import threading
import re
from flask import Flask, render_template, request, jsonify, send_file, url_for
from werkzeug.utils import secure_filename
from google.cloud import speech
from google.cloud.speech import RecognitionConfig
from google.oauth2 import service_account
from google.cloud import storage
import yt_dlp
import docx
from docx.shared import Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
import traceback
from config import config as app_config
import magic
from langdetect import detect, LangDetectException

# Определение конфигурации в зависимости от окружения
config_name = os.environ.get('FLASK_CONFIG', 'default')
config = app_config[config_name]

# Инициализация Flask приложения
app = Flask(__name__)
app.config.from_object(config)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = config.MAX_CONTENT_LENGTH
app.config['CREDENTIALS_PATH'] = config.CREDENTIALS_PATH
app.config['SESSION_EXPIRY'] = config.SESSION_EXPIRY

# Создание папки для загрузок, если её нет
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(tempfile.gettempdir(), 'transcripts'), exist_ok=True)

# Разрешенные расширения файлов
ALLOWED_EXTENSIONS = {'wav', 'mp3', 'ogg', 'flac', 'm4a', 'aac', 'opus', 'webm'}

# Словарь для хранения статусов задач и сессий
task_status = {}
sessions = {}

def generate_task_id():
    """Генерация уникального ID задачи"""
    return str(uuid.uuid4())

def generate_session_id():
    """Генерация уникального ID сессии"""
    return str(uuid.uuid4())

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_credentials():
    """Получение учетных данных Google Cloud из JSON-файла."""
    try:
        return service_account.Credentials.from_service_account_file(app.config['CREDENTIALS_PATH'])
    except Exception as e:
        print(f"Ошибка при получении учетных данных: {e}")
        return None

def format_time(seconds):
    """Форматирование времени в формат ММ:СС"""
    minutes = int(seconds) // 60
    seconds = int(seconds) % 60
    return f"{minutes:02d}:{seconds:02d}"

def get_audio_sample_rate(file_path):
    """Определение частоты дискретизации аудиофайла"""
    try:
        from pydub import AudioSegment
        audio = AudioSegment.from_file(file_path)
        return audio.frame_rate
    except Exception as e:
        print(f"Ошибка при определении частоты дискретизации: {e}")
        return None  # Вернем None и позволим API определить частоту самостоятельно

def check_and_convert_audio_channels(file_path, status_callback=None):
    """
    Проверяет количество каналов в аудиофайле и при необходимости конвертирует в моно
    Использует ffmpeg напрямую для более надежной обработки
    """
    try:
        # Проверка количества каналов с помощью ffprobe
        import subprocess
        import json
        
        if status_callback:
            status_callback(8, "Проверка аудиофайла...")
        
        # Используем ffprobe для получения информации о файле
        cmd = [
            'ffprobe', '-v', 'quiet', '-print_format', 'json',
            '-show_streams', file_path
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        info = json.loads(result.stdout)
        
        # Определяем, есть ли аудио поток и сколько каналов
        audio_stream = None
        for stream in info.get('streams', []):
            if stream.get('codec_type') == 'audio':
                audio_stream = stream
                break
        
        if not audio_stream:
            if status_callback:
                status_callback(10, "Предупреждение: аудио поток не найден в файле")
            return file_path
        
        channels = audio_stream.get('channels', 0)
        
        # Если уже моно, просто возвращаем путь к файлу
        if channels == 1:
            if status_callback:
                status_callback(10, "Файл уже в монофоническом формате")
            return file_path
        
        # Конвертируем в моно, если больше одного канала
        if channels > 1:
            if status_callback:
                status_callback(9, f"Файл имеет {channels} каналов. Конвертация в моно...")
            
            output_path = file_path + '.mono.wav'
            cmd = [
                'ffmpeg', '-y', '-i', file_path, 
                '-ac', '1', '-ar', '16000', 
                '-vn', '-acodec', 'pcm_s16le', output_path
            ]
            
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if status_callback:
                status_callback(10, "Файл успешно преобразован в монофонический формат")
            
            return output_path
        
        # По умолчанию возвращаем исходный файл
        return file_path
    
    except Exception as e:
        print(f"Ошибка при проверке/конвертации аудио: {e}")
        if status_callback:
            status_callback(10, f"Предупреждение: {str(e)}. Используем исходный файл.")
        return file_path

def prepare_audio_for_transcription(file_path, status_callback=None):
    """Подготовка аудиофайла для транскрипции: конвертация в подходящий формат"""
    try:
        # Проверяем наличие расширения для определения формата
        from pydub import AudioSegment
        
        if status_callback:
            status_callback(5, "Анализ аудиофайла...")
        
        # Получаем расширение файла
        file_ext = os.path.splitext(file_path)[1].lower()
        
        try:
            if status_callback:
                status_callback(8, f"Преобразование аудио в оптимальный формат...")
            
            output_path = file_path + '.mono.wav'
            
            # Загружаем аудио с помощью pydub
            if file_ext == '.mp3':
                audio = AudioSegment.from_mp3(file_path)
            elif file_ext == '.m4a':
                audio = AudioSegment.from_file(file_path, format="m4a")
            elif file_ext == '.ogg':
                audio = AudioSegment.from_ogg(file_path)
            elif file_ext == '.flac':
                audio = AudioSegment.from_file(file_path, format="flac")
            elif file_ext == '.webm':
                audio = AudioSegment.from_file(file_path, format="webm")
            elif file_ext == '.opus':
                audio = AudioSegment.from_file(file_path, format="opus")
            elif file_ext == '.wav':
                audio = AudioSegment.from_wav(file_path)
            else:
                audio = AudioSegment.from_file(file_path)
            
            # Всегда преобразуем в моно, независимо от исходного формата
            audio = audio.set_channels(1)  # 1 канал (моно)
            audio = audio.set_sample_width(2)  # 16 bit
            audio = audio.set_frame_rate(16000)  # 16 kHz частота дискретизации
            
            # Сохраняем в моно WAV
            audio.export(output_path, format="wav")
            
            if status_callback:
                status_callback(10, "Аудио успешно преобразовано в формат WAV mono для распознавания")
            
            return output_path
        except Exception as e:
            print(f"Ошибка при конвертации аудио: {e}")
            traceback.print_exc()
            if status_callback:
                status_callback(10, f"Ошибка конвертации: {str(e)}. Попытка конвертации с другими параметрами.")
            
            # Попытка аварийной конвертации через ffmpeg
            try:
                import subprocess
                output_path = file_path + '.mono.wav'
                cmd = [
                    'ffmpeg', '-y', '-i', file_path, 
                    '-ac', '1', '-ar', '16000', 
                    '-vn', '-acodec', 'pcm_s16le', output_path
                ]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                if status_callback:
                    status_callback(10, "Аудио успешно преобразовано через ffmpeg")
                
                return output_path
            except Exception as e2:
                print(f"Ошибка при использовании ffmpeg: {e2}")
                if status_callback:
                    status_callback(10, f"Ошибка резервной конвертации: {str(e2)}. Используем исходный файл.")
                return file_path
    
    except ImportError as ie:
        # Если pydub не установлен
        print(f"Предупреждение: библиотека не установлена ({ie}). Конвертация аудио недоступна.")
        try:
            # Попытка использовать ffmpeg напрямую
            import subprocess
            output_path = file_path + '.mono.wav'
            cmd = [
                'ffmpeg', '-y', '-i', file_path, 
                '-ac', '1', '-ar', '16000', 
                '-vn', '-acodec', 'pcm_s16le', output_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if status_callback:
                status_callback(10, "Аудио успешно преобразовано через ffmpeg")
            
            return output_path
        except Exception as e:
            print(f"Ошибка при использовании ffmpeg: {e}")
            return file_path

def check_audio_for_speech(file_path, status_callback=None):
    """Проверка аудиофайла на наличие речи и шумов"""
    try:
        from pydub import AudioSegment
        from pydub.silence import detect_nonsilent
        
        if status_callback:
            status_callback(12, "Проверка аудио на наличие речи...")
        
        try:
            audio = AudioSegment.from_file(file_path)
            
            # Проверяем на наличие не-тишины
            non_silent_parts = detect_nonsilent(audio, min_silence_len=500, silence_thresh=-40)
            
            if not non_silent_parts:
                if status_callback:
                    status_callback(15, "В аудиофайле не обнаружена речь (только тишина)")
                return False, "В аудиофайле не обнаружена речь (только тишина)"
            
            # Проверяем среднюю громкость
            if audio.dBFS < -30:
                if status_callback:
                    status_callback(15, "Аудиофайл имеет очень низкую громкость")
                return True, "Аудиофайл имеет очень низкую громкость, распознавание может быть неточным"
            
            if status_callback:
                status_callback(15, "Аудиофайл содержит речь с нормальным уровнем громкости")
            return True, "Аудиофайл содержит речь"
        except Exception as e:
            print(f"Ошибка при проверке аудио: {e}")
            return True, "Не удалось проверить аудиофайл на наличие речи"
    except ImportError:
        # Если pydub не установлен
        return True, "Предупреждение: библиотека pydub не установлена. Проверка аудио недоступна."

def detect_speaker_names(transcript):
    """
    Попытка определить имена говорящих из контекста разговора
    Это упрощенная версия - в реальной системе нужен более сложный алгоритм NLP
    """
    if isinstance(transcript, list):
        # Ищем имена в формате "Имя:"
        name_pattern = re.compile(r'([А-Я][а-я]+):', re.UNICODE)
        potential_names = set()
        
        for segment in transcript:
            if 'text' in segment:
                matches = name_pattern.findall(segment['text'])
                for match in matches:
                    if len(match) > 2:  # Фильтруем слишком короткие "имена"
                        potential_names.add(match)
        
        # Если нашли имена, заменяем "Говорящий X" на имена
        if potential_names:
            names_list = list(potential_names)
            speaker_map = {}
            
            # Создаем соответствие "Говорящий X" -> "Имя"
            for i, segment in enumerate(transcript):
                if 'speaker' in segment and segment['speaker'].startswith('Говорящий '):
                    speaker_num = segment['speaker'].split(' ')[1]
                    if speaker_num.isdigit():
                        idx = int(speaker_num) - 1
                        if idx < len(names_list) and speaker_num not in speaker_map:
                            speaker_map[speaker_num] = names_list[idx]
            
            # Заменяем имена говорящих
            for segment in transcript:
                if 'speaker' in segment and segment['speaker'].startswith('Говорящий '):
                    speaker_num = segment['speaker'].split(' ')[1]
                    if speaker_num in speaker_map:
                        segment['speaker'] = speaker_map[speaker_num]
    
    return transcript

def detect_audio_language(file_path):
    """Определение языка аудио с улучшенной логикой"""
    try:
        # Сначала проверяем, указан ли язык в метаданных или имени файла
        basename = os.path.basename(file_path).lower()
        
        # Проверка на явные указания языка в имени файла
        if any(lang in basename for lang in ['рус', 'rus', 'russian', '.ru']):
            return 'ru-RU'
        if any(lang in basename for lang in ['eng', 'english', '.en']):
            return 'en-US'
        
        # По умолчанию для большинства случаев используем русский язык
        return 'ru-RU'  # Всегда возвращаем русский язык по умолчанию
    except Exception as e:
        print(f"Ошибка при определении языка аудио: {e}")
        return 'ru-RU'  # В случае ошибки также используем русский

def transcribe_audio(file_path, language_code='ru-RU', enable_timestamps=False, status_callback=None):
    """Транскрибирование аудиофайла с помощью Google Speech-to-Text API."""
    # Функция-обертка для обновления статуса
    def update_status(percent, message):
        print(f"[Прогресс] {percent}%: {message}")
        if status_callback:
            status_callback(percent, message)
    
    update_status(2, f"Начало обработки аудиофайла (язык: {language_code})")
    
    credentials = get_credentials()
    if not credentials:
        return "Ошибка авторизации в Google Cloud."
    
    # Проверка и конвертация каналов аудио
    file_path = check_and_convert_audio_channels(file_path, update_status)
    
    # Подготовка аудиофайла (конвертация)
    prepared_file_path = prepare_audio_for_transcription(file_path, update_status)
    update_status(10, "Аудиофайл преобразован в оптимальный формат")
    
    # Проверка аудио на наличие речи
    has_speech, speech_message = check_audio_for_speech(prepared_file_path, update_status)
    if not has_speech:
        return speech_message
    
    client = speech.SpeechClient(credentials=credentials)
    
    # Получаем длительность аудио в секундах
    try:
        from pydub import AudioSegment
        audio_segment = AudioSegment.from_file(prepared_file_path)
        audio_duration_seconds = len(audio_segment) / 1000  # длительность в секундах
        update_status(18, f"Определена длительность аудио: {audio_duration_seconds:.1f} секунд")
    except Exception as e:
        print(f"Ошибка при определении длительности: {e}")
        # Если не удалось определить длительность, предполагаем, что она большая
        audio_duration_seconds = 61  # предполагаем, что больше минуты
        update_status(18, "Не удалось определить длительность. Предполагаем, что файл длинный.")
    
    # Проверяем размер файла
    file_size = os.path.getsize(prepared_file_path)
    file_name = os.path.basename(prepared_file_path)
    
    update_status(20, f"Подготовка файла {file_name} (размер: {file_size/1024/1024:.2f} МБ)")
    
    # Если размер файла превышает 10 МБ или длительность больше 60 секунд, используем Cloud Storage
    if file_size > 10 * 1024 * 1024 or audio_duration_seconds > 60:
        update_status(25, f"Файл требует загрузки в Cloud Storage (размер или длительность)")
        
        # Используем созданный бакет
        gcs_bucket_name = "audio_transscript"
        # Используем временную метку в имени файла для более удобной организации
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        gcs_file_name = f"audio/saved/{timestamp}_{file_name}"
            
        try:
            # Загружаем файл в Google Cloud Storage
            update_status(30, "Загрузка файла в Cloud Storage...")
            storage_client = storage.Client(credentials=credentials)
            bucket = storage_client.bucket(gcs_bucket_name)
            blob = bucket.blob(gcs_file_name)
            
            # Загрузка файла
            blob.upload_from_filename(prepared_file_path)
            update_status(40, "Загрузка файла в Cloud Storage завершена")
            
            # Создаем ссылку на аудио в GCS
            gcs_uri = f"gs://{gcs_bucket_name}/{gcs_file_name}"
            update_status(42, f"Файл загружен как: {gcs_uri}")
            audio = speech.RecognitionAudio(uri=gcs_uri)
            
        except Exception as e:
            print(f"Ошибка при загрузке в Cloud Storage: {e}")
            traceback.print_exc()
            return f"Ошибка при загрузке файла в Cloud Storage: {str(e)}"
    else:
        update_status(25, "Файл подходит для прямой отправки в API")
        # Если файл небольшой, используем прямую отправку
        with open(prepared_file_path, 'rb') as audio_file:
            content = audio_file.read()
        audio = speech.RecognitionAudio(content=content)
        update_status(40, "Файл подготовлен для отправки в API")
    
    # Определение частоты дискретизации аудио
    sample_rate = get_audio_sample_rate(prepared_file_path)
    
    # Базовая конфигурация
    update_status(45, "Настройка параметров распознавания")
    update_status(46, f"Используем выбранный язык для распознавания: {language_code}")
    
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        # Используем определенную частоту или оставляем None, чтобы API определил самостоятельно
        sample_rate_hertz=16000 if not sample_rate else sample_rate,
        language_code=language_code,
        enable_automatic_punctuation=True,
        audio_channel_count=1,  # Всегда используем 1 канал (моно)
        # Увеличиваем чувствительность распознавания для тихих аудио
        use_enhanced=True,
        # Добавляем параметр для улучшения работы с тихим аудио
        speech_contexts=[speech.SpeechContext(
            phrases=["", " "],  # Пустые фразы для повышения чувствительности
            boost=10.0  # Повышаем чувствительность распознавания
        )],
        # Включаем профильтрованные модели для улучшения качества
        model="default",
        # Увеличиваем уровень обнаружения речи
        max_alternatives=2  # Получаем альтернативные варианты распознавания
    )
    
    # Добавление таймингов если необходимо
    if enable_timestamps:
        config.enable_word_time_offsets = True
        
        # Проверяем доступность диаризации в текущей версии API
        try:
            # Настройка для диаризации говорящих
            diarization_config = speech.SpeakerDiarizationConfig(
                enable_speaker_diarization=True,
                min_speaker_count=2,
                max_speaker_count=10,
            )
            config.diarization_config = diarization_config
            update_status(48, "Включена диаризация говорящих")
        except (AttributeError, ValueError) as e:
            update_status(48, f"Диаризация недоступна: {e}. Используем простое определение таймингов.")
    
    try:
        # Определяем, используется ли GCS (был ли загружен файл в облако)
        is_gcs_used = 'gcs_uri' in locals()
        
        # Для файлов в Cloud Storage или длинных файлов всегда используем асинхронное распознавание
        if is_gcs_used or audio_duration_seconds > 60:
            update_status(50, "Запуск асинхронного распознавания")
            operation = client.long_running_recognize(config=config, audio=audio)
            
            update_status(52, "Ожидание завершения распознавания...")
            
            # Отслеживаем прогресс распознавания
            start_time = time.time()
            done = False
            last_percent = 52
            
            while not done:
                if operation.done():
                    done = True
                    update_status(90, "Распознавание завершено")
                else:
                    elapsed = time.time() - start_time
                    # Оцениваем примерное время распознавания в зависимости от размера файла или длительности
                    estimated_total = max(audio_duration_seconds * 0.5, 60)  # примерно половина от длительности аудио, но минимум 60 сек
                    
                    percent = 52 + min(int((elapsed / estimated_total) * 38), 37)  # от 52% до 89%
                    if percent > last_percent:
                        update_status(percent, f"Распознавание: прошло {int(elapsed)} сек.")
                        last_percent = percent
                    
                    time.sleep(5)  # Проверяем каждые 5 секунд
            
            response = operation.result(timeout=300)  # Увеличиваем таймаут для больших файлов
        else:
            # Для коротких локальных файлов используем синхронное распознавание
            update_status(50, "Запуск синхронного распознавания для короткого аудио")
            response = client.recognize(config=config, audio=audio)
            update_status(90, "Распознавание завершено")
        
        # Проверяем, есть ли результаты распознавания
        if not response.results:
            update_status(95, "Предупреждение: речь не распознана")
            print("Предупреждение: API не вернул результатов распознавания")
            
            # Пробуем с другими настройками
            update_status(96, "Повторная попытка с другими параметрами...")
            
            # Изменяем конфигурацию
            config = speech.RecognitionConfig(
                encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=16000,
                language_code=language_code,
                enable_automatic_punctuation=True,
                audio_channel_count=1,
                use_enhanced=True,
                model="latest_short",  # Используем другую модель
                speech_contexts=[speech.SpeechContext(
                    phrases=["", " "],
                    boost=20.0  # Увеличиваем чувствительность еще больше
                )]
            )
            
            # Повторяем запрос с новыми параметрами
            try:
                update_status(97, "Повторная попытка распознавания...")
                response = client.recognize(config=config, audio=audio)
                update_status(98, "Повторное распознавание завершено")
                
                if not response.results:
                    return "Речь не распознана. Возможные причины: тишина в аудио, шум, несоответствие языка."
            except Exception as e:
                print(f"Ошибка при повторном распознавании: {e}")
                return "Речь не распознана. Возможные причины: тишина в аудио, шум, несоответствие языка."
        
        update_status(95, "Обработка результатов распознавания")
        
        # Обработка результатов
        if enable_timestamps:
            # Вариант с таймингами
            result = []
            current_speaker = 1
            
            for i, result_item in enumerate(response.results):
                if not result_item.alternatives:
                    continue
                    
                alternative = result_item.alternatives[0]
                
                # Проверка наличия информации о говорящих
                if hasattr(result_item, 'alternatives') and hasattr(alternative, 'words') and len(alternative.words) > 0:
                    # Проверяем наличие speaker_tag в словах
                    has_speaker_tags = hasattr(alternative.words[0], 'speaker_tag')
                    
                    if has_speaker_tags:
                        # Группировка слов по говорящим
                        current_speaker = None
                        current_text = ""
                        current_start_time = 0
                        speaker_segments = []
                        
                        for word in alternative.words:
                            if current_speaker is None:
                                current_speaker = word.speaker_tag
                                current_text = word.word + " "
                                current_start_time = word.start_time.total_seconds()
                            elif word.speaker_tag != current_speaker:
                                # Новый говорящий - сохраняем предыдущий сегмент
                                speaker_segments.append({
                                    "speaker": f"Говорящий {current_speaker}",
                                    "text": current_text.strip(),
                                    "start_time": format_time(current_start_time)
                                })
                                
                                current_speaker = word.speaker_tag
                                current_text = word.word + " "
                                current_start_time = word.start_time.total_seconds()
                            else:
                                current_text += word.word + " "
                        
                        # Добавляем последний сегмент
                        if current_text:
                            speaker_segments.append({
                                "speaker": f"Говорящий {current_speaker}",
                                "text": current_text.strip(),
                                "start_time": format_time(current_start_time)
                            })
                            
                        result.extend(speaker_segments)
                    else:
                        # Без speaker_tag, но с таймингами слов
                        start_time = 0
                        if alternative.words:
                            start_time = alternative.words[0].start_time.total_seconds()
                        
                        # Определяем говорящего по очереди (имитация)
                        if i > 0 and len(result) > 0:
                            current_speaker = 2 if current_speaker == 1 else 1
                        result.append({
                            "speaker": f"Говорящий {current_speaker}",
                            "text": alternative.transcript,
                            "start_time": format_time(start_time)
                        })
                else:
                    # Без информации о словах и временных метках
                    if i > 0 and len(result) > 0:
                        current_speaker = 2 if current_speaker == 1 else 1
                    
                    result.append({
                        "speaker": f"Говорящий {current_speaker}",
                        "text": alternative.transcript,
                        "start_time": "00:00"
                    })
            
            segments_count = len(result)
            update_status(98, f"Обработка завершена: получено {segments_count} сегментов с таймингами")
            
            # Если не получено сегментов, возвращаем простой текст
            if segments_count == 0:
                transcript = ""
                for res in response.results:
                    transcript += res.alternatives[0].transcript + " "
                return transcript.strip()
            
            # Попытка определить имена говорящих из контекста
            result = detect_speaker_names(result)
            
            return result
        else:
            # Обычная транскрипция без таймингов
            transcript = ""
            for result in response.results:
                transcript += result.alternatives[0].transcript + " "
                
            transcript = transcript.strip()
            words_count = len(transcript.split())
            update_status(98, f"Обработка завершена: получено {words_count} слов")
            
            if words_count == 0:
                return "Речь не распознана. Возможные причины: тишина в аудио, шум, несоответствие языка."
                
            return transcript
            
    except Exception as e:
        print(f"Ошибка при транскрибировании: {e}")
        traceback.print_exc()
        return f"Ошибка при транскрибировании: {str(e)}"
    finally:
        # Используем Cloud Storage, НЕ удаляем файл
        if 'gcs_uri' in locals():
            update_status(100, f"Аудиофайл сохранен в Cloud Storage: {gcs_uri}")
        
        # Удаляем временный конвертированный файл, если он создавался
        if prepared_file_path != file_path and os.path.exists(prepared_file_path):
            try:
                os.remove(prepared_file_path)
            except Exception as e:
                print(f"Не удалось удалить временный файл: {e}")

def analyze_transcript(transcript, with_timestamps=False):
    """Расширенный анализ транскрипции с дополнительными метриками"""
    try:
        result = {}
        
        if with_timestamps and isinstance(transcript, list):
            # Статистика по говорящим
            speakers = {}
            word_frequencies = {}
            sentence_lengths = []
            total_words = 0
            total_time = 0  # Общая длительность в секундах
            
            for segment in transcript:
                speaker = segment['speaker']
                text = segment['text']
                
                # Преобразование времени (format: "MM:SS")
                start_time_str = segment.get('start_time', '00:00')
                try:
                    minutes, seconds = map(int, start_time_str.split(':'))
                    start_time_sec = minutes * 60 + seconds
                except (ValueError, AttributeError):
                    start_time_sec = 0
                
                # Разбиваем текст на слова и предложения
                words = re.findall(r'\b[а-яА-Яa-zA-Z]+\b', text.lower())
                sentences = re.split(r'[.!?]+', text)
                
                # Подсчет для говорящего
                if speaker not in speakers:
                    speakers[speaker] = {
                        'word_count': 0,
                        'sentence_count': 0,
                        'total_time': 0,
                        'avg_words_per_sentence': 0,
                        'speech_rate': 0,  # Слов в минуту
                        'segments': 0
                    }
                
                speakers[speaker]['word_count'] += len(words)
                speakers[speaker]['sentence_count'] += len(sentences)
                speakers[speaker]['segments'] += 1
                
                # Оценка времени (очень приблизительно)
                if len(transcript) > 1:  # Если есть несколько сегментов
                    # Находим следующий сегмент для того же говорящего
                    next_segment_idx = -1
                    for i, seg in enumerate(transcript):
                        if seg == segment:  # Нашли текущий сегмент
                            # Ищем следующий с тем же говорящим
                            for j in range(i+1, len(transcript)):
                                if transcript[j]['speaker'] == speaker:
                                    next_segment_idx = j
                                    break
                            break
                    
                    if next_segment_idx > 0:
                        # Найден следующий сегмент того же говорящего
                        next_start_time_str = transcript[next_segment_idx].get('start_time', '00:00')
                        try:
                            next_minutes, next_seconds = map(int, next_start_time_str.split(':'))
                            next_start_time_sec = next_minutes * 60 + next_seconds
                            segment_duration = next_start_time_sec - start_time_sec
                            if segment_duration > 0:
                                speakers[speaker]['total_time'] += segment_duration
                                total_time += segment_duration
                        except (ValueError, AttributeError):
                            pass
                
                # Подсчет общей частоты слов
                for word in words:
                    if len(word) > 2:  # Игнорируем слишком короткие слова
                        word_frequencies[word] = word_frequencies.get(word, 0) + 1
                
                # Длина предложений
                for sentence in sentences:
                    if sentence.strip():
                        words_in_sentence = len(re.findall(r'\b[а-яА-Яa-zA-Z]+\b', sentence.lower()))
                        if words_in_sentence > 0:
                            sentence_lengths.append(words_in_sentence)
                
                total_words += len(words)
            
            # Расчет среднего времени между сегментами (если доступно)
            average_segment_duration = 0
            if len(transcript) > 1:
                # Сортируем сегменты по времени
                sorted_segments = sorted(transcript, key=lambda x: x.get('start_time', '00:00'))
                total_duration = 0
                segments_with_time = 0
                
                for i in range(1, len(sorted_segments)):
                    current_time_str = sorted_segments[i].get('start_time', '')
                    prev_time_str = sorted_segments[i-1].get('start_time', '')
                    
                    if current_time_str and prev_time_str:
                        try:
                            # Вычисляем разницу времени
                            current_minutes, current_seconds = map(int, current_time_str.split(':'))
                            current_time_sec = current_minutes * 60 + current_seconds
                            
                            prev_minutes, prev_seconds = map(int, prev_time_str.split(':'))
                            prev_time_sec = prev_minutes * 60 + prev_seconds
                            
                            duration = current_time_sec - prev_time_sec
                            if duration > 0:
                                total_duration += duration
                                segments_with_time += 1
                        except (ValueError, AttributeError):
                            pass
                
                if segments_with_time > 0:
                    average_segment_duration = total_duration / segments_with_time
            
            # Расчет средних значений
            for speaker, stats in speakers.items():
                if stats['sentence_count'] > 0:
                    stats['avg_words_per_sentence'] = round(stats['word_count'] / stats['sentence_count'], 2)
                
                if stats['total_time'] > 0:
                    # Расчет скорости речи (слов в минуту)
                    stats['speech_rate'] = round(stats['word_count'] / (stats['total_time'] / 60), 1)
            
            # Выявление ключевых фраз (простой алгоритм)
            keywords = {}
            for word, count in word_frequencies.items():
                if count > 2 and len(word) > 3:  # Минимальный порог для ключевых слов
                    keywords[word] = count
            
            # Формирование "облака тегов"
            sorted_keywords = sorted(keywords.items(), key=lambda x: x[1], reverse=True)
            top_keywords = dict(sorted_keywords[:30])
            
            # Сортируем частоты слов
            sorted_words = sorted(word_frequencies.items(), key=lambda x: x[1], reverse=True)
            top_words = dict(sorted_words[:50])
            
            # Определение языка транскрипции
            language = "unknown"
            try:
                from langdetect import detect
                # Объединяем весь текст для более точного определения
                full_text = " ".join([segment['text'] for segment in transcript])
                if full_text.strip():
                    language = detect(full_text)
            except (ImportError, Exception) as e:
                print(f"Не удалось определить язык: {e}")
            
            # Формируем результат
            result = {
                'speakers': speakers,
                'top_words': top_words,
                'keywords': top_keywords,
                'total_words': total_words,
                'avg_sentence_length': round(sum(sentence_lengths) / len(sentence_lengths), 2) if sentence_lengths else 0,
                'sentence_count': len(sentence_lengths),
                'word_variety': round(len(word_frequencies) / total_words, 3) if total_words > 0 else 0,
                'avg_segment_duration': round(average_segment_duration, 2) if average_segment_duration > 0 else 0,
                'estimated_total_duration': total_time,
                'language': language
            }
        else:
            # Анализ для обычного текста без таймингов
            words = re.findall(r'\b[а-яА-Яa-zA-Z]+\b', transcript.lower())
            sentences = re.split(r'[.!?]+', transcript)
            
            # Подсчет частоты слов
            word_frequencies = {}
            for word in words:
                if len(word) > 2:
                    word_frequencies[word] = word_frequencies.get(word, 0) + 1
            
            # Сортируем частоты слов
            sorted_words = sorted(word_frequencies.items(), key=lambda x: x[1], reverse=True)
            top_words = dict(sorted_words[:50])
            
            # Выявление ключевых фраз
            keywords = {}
            for word, count in word_frequencies.items():
                if count > 2 and len(word) > 3:
                    keywords[word] = count
            
            sorted_keywords = sorted(keywords.items(), key=lambda x: x[1], reverse=True)
            top_keywords = dict(sorted_keywords[:30])
            
            # Длина предложений
            sentence_lengths = []
            for sentence in sentences:
                if sentence.strip():
                    words_in_sentence = len(re.findall(r'\b[а-яА-Яa-zA-Z]+\b', sentence.lower()))
                    if words_in_sentence > 0:
                        sentence_lengths.append(words_in_sentence)
            
            # Определение языка транскрипции
            language = "unknown"
            try:
                from langdetect import detect
                if transcript.strip():
                    language = detect(transcript)
            except (ImportError, Exception) as e:
                print(f"Не удалось определить язык: {e}")
            
            # Формируем результат
            result = {
                'top_words': top_words,
                'keywords': top_keywords,
                'total_words': len(words),
                'avg_sentence_length': round(sum(sentence_lengths) / len(sentence_lengths), 2) if sentence_lengths else 0,
                'sentence_count': len(sentence_lengths),
                'word_variety': round(len(word_frequencies) / len(words), 3) if words else 0,
                'language': language
            }
        
        return result
    except Exception as e:
        print(f"Ошибка при анализе транскрипции: {e}")
        traceback.print_exc()
        return {
            'status': 'error',
            'message': f'Ошибка при анализе: {str(e)}'
        }

def get_video_info(url):
    """Получение информации о видео по ссылке"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'geo_bypass': True,
        'nocheckcertificate': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                'title': info.get('title', 'Неизвестное видео'),
                'uploader': info.get('uploader', 'Неизвестный автор'),
                'duration': info.get('duration', 0),
                'upload_date': info.get('upload_date', ''),
                'thumbnail': info.get('thumbnail', '')
            }
    except Exception as e:
        print(f"Ошибка при получении информации о видео: {e}")
        return None

def download_from_youtube(url, status_callback=None):
    """Загрузка аудио из YouTube-видео."""
    if status_callback:
        status_callback(10, "Подготовка к загрузке видео...")
    
    # Получаем информацию о видео
    video_info = get_video_info(url)
    if video_info:
        if status_callback:
            status_callback(12, f"Найдено видео: {video_info['title']}")
    
    temp_dir = tempfile.gettempdir()
    output_file = os.path.join(temp_dir, f"{uuid.uuid4()}.%(ext)s")
    
    # Настройка yt-dlp без некорректного постпроцессора
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_file,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'quiet': False,
        'no_warnings': False,
        'geo_bypass': True,
        'nocheckcertificate': True,
        'progress_hooks': [lambda d: status_callback(
            min(10 + int(d.get('downloaded_percent', 0) * 0.3), 40), 
            f"Загрузка видео: {d.get('downloaded_percent', 0):.1f}%"
        ) if status_callback and 'downloaded_percent' in d else None],
    }
    
    try:
        if status_callback:
            status_callback(15, "Загрузка видео...")
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_file = ydl.prepare_filename(info).rsplit('.', 1)[0] + '.wav'
            
            if status_callback:
                status_callback(40, "Видео загружено и преобразовано в аудио")
            
            # Ручное преобразование в моно с помощью ffmpeg
            try:
                import subprocess
                
                if status_callback:
                    status_callback(41, "Преобразование аудио в монофонический формат...")
                
                mono_file = downloaded_file + '.mono.wav'
                cmd = [
                    'ffmpeg', '-y', '-i', downloaded_file, 
                    '-ac', '1', '-ar', '16000', 
                    '-vn', '-acodec', 'pcm_s16le', mono_file
                ]
                
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                # Проверяем, что файл создан
                if os.path.exists(mono_file):
                    os.replace(mono_file, downloaded_file)
                    if status_callback:
                        status_callback(42, "Аудио успешно преобразовано в моно формат")
                else:
                    if status_callback:
                        status_callback(42, "Не удалось преобразовать в моно. Используем исходный файл.")
            except Exception as e:
                print(f"Ошибка при преобразовании в моно: {e}")
                if status_callback:
                    status_callback(42, f"Предупреждение: {str(e)}. Попытка использовать pydub...")
                
                # Запасной вариант с использованием pydub
                try:
                    from pydub import AudioSegment
                    audio = AudioSegment.from_wav(downloaded_file)
                    audio = audio.set_channels(1)
                    audio = audio.set_frame_rate(16000)
                    audio.export(downloaded_file, format="wav")
                    if status_callback:
                        status_callback(43, "Аудио преобразовано в моно формат с помощью pydub")
                except Exception as e2:
                    print(f"Ошибка при использовании pydub: {e2}")
                    if status_callback:
                        status_callback(43, "Не удалось преобразовать аудио в моно. Продолжаем с исходным файлом.")
            
            return downloaded_file, video_info
    except Exception as e:
        print(f"Ошибка при загрузке видео: {e}")
        traceback.print_exc()
        if status_callback:
            status_callback(0, f"Ошибка при загрузке видео: {str(e)}")
        return None, None

def create_docx(transcript, filename="transcript", with_timestamps=False, video_info=None):
    """Создание DOCX файла с транскрипцией."""
    doc = docx.Document()
    
    # Стилизация заголовка
    title = doc.add_heading("Транскрипция аудио", 0)
    title_paragraph = title.paragraph_format
    title_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    
    # Добавление информации о видео, если она есть
    if video_info:
        video_paragraph = doc.add_paragraph()
        video_paragraph.add_run("Информация о видео:\n").bold = True
        video_paragraph.add_run(f"Название: {video_info['title']}\n")
        video_paragraph.add_run(f"Автор: {video_info['uploader']}\n")
        
        if video_info['duration']:
            minutes, seconds = divmod(video_info['duration'], 60)
            video_paragraph.add_run(f"Длительность: {minutes}:{seconds:02d}\n")
        
        if video_info['upload_date']:
            upload_date = video_info['upload_date']
            formatted_date = f"{upload_date[6:8]}.{upload_date[4:6]}.{upload_date[0:4]}"
            video_paragraph.add_run(f"Дата публикации: {formatted_date}\n")
    
    # Добавление даты и времени
    date_paragraph = doc.add_paragraph()
    date_run = date_paragraph.add_run(f"Дата транскрипции: {datetime.datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    date_run.font.size = Pt(10)
    date_run.font.italic = True
    date_paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    
    # Горизонтальная линия
    doc.add_paragraph("_" * 80)
    
    # Добавление транскрибированного текста с красивым оформлением
    if with_timestamps and isinstance(transcript, list):
        # Оформление с таймингами и разными говорящими
        for segment in transcript:
            paragraph = doc.add_paragraph()
            
            # Добавление тайминга
            time_run = paragraph.add_run(f"[{segment['start_time']}] ")
            time_run.font.bold = True
            time_run.font.size = Pt(10)
            time_run.font.color.rgb = RGBColor(100, 100, 100)
            
            # Добавление говорящего
            speaker_run = paragraph.add_run(f"{segment['speaker']}: ")
            speaker_run.font.bold = True
            speaker_run.font.color.rgb = RGBColor(0, 0, 150)
            
            # Добавление текста
            text_run = paragraph.add_run(segment['text'])
            text_run.font.size = Pt(11)
            
            # Добавление пустой строки между говорящими
            doc.add_paragraph()
    else:
        # Обычный текст без разделения на говорящих
        paragraph = doc.add_paragraph()
        text_run = paragraph.add_run(transcript)
        text_run.font.size = Pt(11)
    
    # Добавление нижнего колонтитула
    footer = doc.add_paragraph()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run = footer.add_run("Создано с помощью сервиса транскрипции аудио")
    footer_run.font.size = Pt(8)
    footer_run.font.italic = True
    
    # Сохранение во временный файл
    temp_file = os.path.join(tempfile.gettempdir(), 'transcripts', f"{filename}.docx")
    doc.save(temp_file)
    
    return temp_file

def save_transcript_to_session(session_id, transcript, docx_path, with_timestamps=False, video_info=None, language_code='ru-RU'):
    """Сохранение транскрипции в сессию с информацией о языке"""
    # Формируем уникальный URL для доступа к сессии
    share_url = f"/share/{session_id}"
    
    sessions[session_id] = {
        'created_at': datetime.datetime.now().timestamp(),
        'transcript': transcript,
        'docx_path': docx_path,
        'with_timestamps': with_timestamps,
        'video_info': video_info,
        'share_url': share_url,
        'language': language_code  # Добавляем информацию о языке
    }
    
    # Очистка старых сессий (старше 24 часов)
    current_time = datetime.datetime.now().timestamp()
    sessions_to_delete = []
    
    for s_id, s_data in sessions.items():
        if current_time - s_data['created_at'] > app.config['SESSION_EXPIRY']:
            sessions_to_delete.append(s_id)
    
    for s_id in sessions_to_delete:
        del sessions[s_id]
    
    return share_url

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/share/<session_id>')
def shared_transcript(session_id):
    """Страница с доступом к сохраненной транскрипции"""
    if session_id in sessions:
        session_data = sessions[session_id]
        return render_template(
            'shared.html',
            transcript=session_data['transcript'],
            with_timestamps=session_data['with_timestamps'],
            video_info=session_data['video_info'],
            docx_path=session_data['docx_path'],
            language=session_data.get('language', 'ru-RU')  # Передаем язык в шаблон
        )
    return render_template('error.html', message="Сессия не найдена или истекла")

@app.route('/task_status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """Получение статуса задачи по ID"""
    if task_id in task_status:
        return jsonify(task_status[task_id])
    return jsonify({'status': 'unknown', 'percent': 0, 'message': 'Задача не найдена'})

def process_audio_file(file_path, enable_timestamps, task_id, language_code='ru-RU'):
    """Обработка аудиофайла в отдельном потоке"""
    try:
        # Функция обновления статуса
        def update_status(percent, message):
            task_status[task_id] = {
                'status': 'transcribing' if percent < 100 else 'complete',
                'percent': percent,
                'message': message
            }
        
        # Обновляем начальный статус
        update_status(5, "Начало транскрибирования")
        
        # Запускаем транскрибирование с указанным языком
        transcript = transcribe_audio(
            file_path, 
            enable_timestamps=enable_timestamps, 
            status_callback=update_status,
            language_code=language_code
        )
        
        # Генерируем ID сессии
        session_id = generate_session_id()
        
        # Создание DOCX файла
        docx_path = create_docx(transcript, os.path.splitext(os.path.basename(file_path))[0], with_timestamps=enable_timestamps)
        
        # Сохраняем транскрипцию в сессию
        share_url = save_transcript_to_session(
            session_id, 
            transcript, 
            os.path.basename(docx_path), 
            enable_timestamps,
            language_code=language_code
        )
        
        # Финальное обновление статуса
        task_status[task_id] = {
            'status': 'complete',
            'percent': 100,
            'message': 'Транскрипция завершена',
            'transcript': transcript,
            'docx_path': os.path.basename(docx_path),
            'with_timestamps': enable_timestamps,
            'session_id': session_id,
            'share_url': share_url,
            'language': language_code
        }
    except Exception as e:
        print(f"Ошибка при обработке файла: {e}")
        traceback.print_exc()
        # В случае ошибки
        task_status[task_id] = {
            'status': 'error',
            'percent': 0,
            'message': f'Ошибка: {str(e)}'
        }

def process_youtube_link(url, enable_timestamps, task_id, language_code='ru-RU'):
    """Обработка ссылки на YouTube в отдельном потоке"""
    try:
        # Функция обновления статуса
        def update_status(percent, message):
            task_status[task_id] = {
                'status': 'transcribing' if percent < 100 else 'complete',
                'percent': percent,
                'message': message
            }
        
        # Обновляем начальный статус
        update_status(5, "Начало обработки ссылки")
        
        # Загрузка аудио из видео
        audio_path, video_info = download_from_youtube(url, update_status)
        
        if not audio_path:
            task_status[task_id] = {
                'status': 'error',
                'percent': 0,
                'message': 'Не удалось загрузить аудио по указанной ссылке'
            }
            return
        
        # Запускаем транскрибирование с указанным языком
        transcript = transcribe_audio(
            audio_path, 
            enable_timestamps=enable_timestamps, 
            status_callback=update_status,
            language_code=language_code
        )
        
        # Генерируем ID сессии
        session_id = generate_session_id()
        
        # Создание DOCX файла
        docx_path = create_docx(transcript, f"link_{uuid.uuid4()}", with_timestamps=enable_timestamps, video_info=video_info)
        
        # Сохраняем транскрипцию в сессию
        share_url = save_transcript_to_session(
            session_id, 
            transcript, 
            os.path.basename(docx_path), 
            enable_timestamps, 
            video_info,
            language_code=language_code
        )
        
        # Удаление временного файла
        try:
            os.remove(audio_path)
        except Exception as e:
            print(f"Ошибка при удалении временного файла: {e}")
        
        # Финальное обновление статуса
        task_status[task_id] = {
            'status': 'complete',
            'percent': 100,
            'message': 'Транскрипция завершена',
            'transcript': transcript,
            'docx_path': os.path.basename(docx_path),
            'with_timestamps': enable_timestamps,
            'video_info': video_info,
            'session_id': session_id,
            'share_url': share_url,
            'language': language_code
        }
    except Exception as e:
        print(f"Ошибка при обработке ссылки: {e}")
        traceback.print_exc()
        # В случае ошибки
        task_status[task_id] = {
            'status': 'error',
            'percent': 0,
            'message': f'Ошибка: {str(e)}'
        }

@app.route('/upload', methods=['POST'])
def upload_file():
    """Обработка загрузки аудиофайла."""
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не найден в запросе'}), 400
    
    file = request.files['file']
    enable_timestamps = request.form.get('timestamps') == 'true'
    # Получаем выбранный язык или используем русский по умолчанию
    language_code = request.form.get('language', 'ru-RU')
    
    if file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4()}_{filename}")
        file.save(file_path)
        
        # Создаем ID задачи
        task_id = generate_task_id()
        
        # Инициализируем статус задачи
        task_status[task_id] = {
            'status': 'preparing',
            'percent': 0,
            'message': 'Подготовка к обработке файла'
        }
        
        # Запускаем обработку в отдельном потоке, передавая язык
        threading.Thread(target=process_audio_file, 
                         args=(file_path, enable_timestamps, task_id, language_code)).start()
        
        # Возвращаем ID задачи клиенту
        return jsonify({
            'task_id': task_id
        })
    
    return jsonify({'error': 'Формат файла не поддерживается'}), 400

@app.route('/record', methods=['POST'])
def process_recording():
    """Обработка записанного аудио."""
    if 'audio_data' not in request.files:
        return jsonify({'error': 'Аудиоданные не найдены в запросе'}), 400
    
    audio_file = request.files['audio_data']
    enable_timestamps = request.form.get('timestamps') == 'true'
    # Получаем выбранный язык или используем русский по умолчанию
    language_code = request.form.get('language', 'ru-RU')
    
    if audio_file.filename == '':
        return jsonify({'error': 'Файл не выбран'}), 400
    
    filename = f"recording_{uuid.uuid4()}.wav"
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    audio_file.save(file_path)
    
    # Создаем ID задачи
    task_id = generate_task_id()
    
    # Инициализируем статус задачи
    task_status[task_id] = {
        'status': 'preparing',
        'percent': 0,
        'message': 'Подготовка к обработке записи'
    }
    
    # Запускаем обработку в отдельном потоке, передавая язык
    threading.Thread(target=process_audio_file, 
                     args=(file_path, enable_timestamps, task_id, language_code)).start()
    
    # Возвращаем ID задачи клиенту
    return jsonify({
        'task_id': task_id
    })

@app.route('/link', methods=['POST'])
def process_link():
    """Обработка ссылки на видео."""
    data = request.json
    
    if not data or 'url' not in data:
        return jsonify({'error': 'URL не найден в запросе'}), 400
    
    url = data['url']
    enable_timestamps = data.get('timestamps', False)
    # Получаем выбранный язык или используем русский по умолчанию
    language_code = data.get('language', 'ru-RU')
    
    # Создаем ID задачи
    task_id = generate_task_id()
    
    # Инициализируем статус задачи
    task_status[task_id] = {
        'status': 'preparing',
        'percent': 0,
        'message': 'Подготовка к загрузке видео'
    }
    
    # Запускаем обработку в отдельном потоке, передавая язык
    threading.Thread(target=process_youtube_link, 
                     args=(url, enable_timestamps, task_id, language_code)).start()
    
    # Возвращаем ID задачи клиенту
    return jsonify({
        'task_id': task_id
    })

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    """Скачивание DOCX файла с транскрипцией."""
    file_path = os.path.join(tempfile.gettempdir(), 'transcripts', filename)
    
    if not os.path.exists(file_path):
        return jsonify({'error': 'Файл не найден'}), 404
    
    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/verify_link', methods=['POST'])
def verify_link():
    """API для проверки ссылки на возможность загрузки"""
    data = request.json
    
    if not data or 'url' not in data:
        return jsonify({'error': 'URL не найден в запросе'}), 400
    
    url = data['url']
    
    try:
        video_info = get_video_info(url)
        if video_info:
            return jsonify({
                'status': 'success',
                'video_info': video_info
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Не удалось получить информацию о видео'
            })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Ошибка при проверке ссылки: {str(e)}'
        })

@app.route('/api/analyze', methods=['POST'])
def analyze_transcript_api():
    """API для анализа транскрипции"""
    data = request.json
    
    if not data or 'transcript' not in data:
        return jsonify({'error': 'Транскрипция не найдена в запросе'}), 400
    
    transcript = data['transcript']
    with_timestamps = data.get('with_timestamps', False)
    
    try:
        # Используем улучшенную функцию анализа
        result = analyze_transcript(transcript, with_timestamps)
        
        return jsonify({
            'status': 'success',
            'analysis': result
        })
    except Exception as e:
        print(f"Ошибка при анализе транскрипции: {e}")
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': f'Ошибка при анализе: {str(e)}'
        }), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)