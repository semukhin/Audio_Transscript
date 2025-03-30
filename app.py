# Внесите следующие изменения в начало app.py:

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

def prepare_audio_for_transcription(file_path, status_callback=None):
    """Подготовка аудиофайла для транскрипции: конвертация в подходящий формат"""
    try:
        # Проверяем наличие расширения для определения формата
        from pydub import AudioSegment
        
        if status_callback:
            status_callback(5, "Анализ аудиофайла...")
        
        # Получаем расширение файла
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Если это не wav, конвертируем
        if file_ext != '.wav':
            try:
                if status_callback:
                    status_callback(8, f"Преобразование аудио из формата {file_ext} в WAV...")
                
                output_path = file_path + '.wav'
                
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
                else:
                    audio = AudioSegment.from_file(file_path)
                
                # Сохраняем оригинальную частоту дискретизации
                # вместо принудительной установки 16000
                audio = audio.set_channels(1)  # 1 канал (моно)
                audio = audio.set_sample_width(2)  # 16 bit
                
                # Сохраняем в WAV
                audio.export(output_path, format="wav")
                
                if status_callback:
                    status_callback(10, "Аудио успешно преобразовано в формат WAV для распознавания")
                
                return output_path
            except Exception as e:
                print(f"Ошибка при конвертации аудио: {e}")
                if status_callback:
                    status_callback(10, f"Ошибка конвертации: {str(e)}. Используем исходный файл.")
                return file_path
        
        return file_path
    except ImportError:
        # Если pydub не установлен
        print("Предупреждение: библиотека pydub не установлена. Конвертация аудио недоступна.")
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

def transcribe_audio(file_path, language_code='ru-RU', enable_timestamps=False, status_callback=None):
    """Транскрибирование аудиофайла с помощью Google Speech-to-Text API."""
    # Функция-обертка для обновления статуса
    def update_status(percent, message):
        print(f"[Прогресс] {percent}%: {message}")
        if status_callback:
            status_callback(percent, message)
    
    update_status(2, "Начало обработки аудиофайла")
    
    credentials = get_credentials()
    if not credentials:
        return "Ошибка авторизации в Google Cloud."
    
    # Подготовка аудиофайла (конвертация)
    prepared_file_path = prepare_audio_for_transcription(file_path, update_status)
    if prepared_file_path != file_path:
        update_status(10, "Аудиофайл преобразован в оптимальный формат")
    
    # Проверка аудио на наличие речи
    has_speech, speech_message = check_audio_for_speech(prepared_file_path, update_status)
    if not has_speech:
        return speech_message
    
    client = speech.SpeechClient(credentials=credentials)
    
    # Проверяем размер файла
    file_size = os.path.getsize(prepared_file_path)
    file_name = os.path.basename(prepared_file_path)
    
    update_status(20, f"Подготовка файла {file_name} (размер: {file_size/1024/1024:.2f} МБ)")
    
    # Если размер файла превышает 10 МБ
    if file_size > 10 * 1024 * 1024:
        update_status(25, f"Файл превышает лимит прямой отправки. Используем Cloud Storage.")
        
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
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        # Используем определенную частоту или оставляем None, чтобы API определил самостоятельно
        sample_rate_hertz=sample_rate if sample_rate else None,
        language_code=language_code,
        enable_automatic_punctuation=True,
        audio_channel_count=1,
        # Увеличиваем чувствительность распознавания для тихих аудио
        use_enhanced=True
    )
    
    # Добавление таймингов если необходимо
    if enable_timestamps:
        config.enable_word_time_offsets = True
        
        # Проверяем доступность диаризации в текущей версии API
        try:
            # В версии v1 это может быть другой формат
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
        # Для файлов в Cloud Storage всегда используем асинхронное распознавание
        if file_size > 10 * 1024 * 1024:
            update_status(50, "Запуск асинхронного распознавания для файла из GCS")
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
                    # Оцениваем примерное время распознавания в зависимости от размера файла
                    # (это приблизительно, так как точное время зависит от многих факторов)
                    estimated_total = file_size / 1024 / 1024 * 2  # ~2 секунды на МБ
                    if estimated_total < 60:
                        estimated_total = 60  # минимум 60 секунд
                    
                    percent = 52 + min(int((elapsed / estimated_total) * 38), 37)  # от 52% до 89%
                    if percent > last_percent:
                        update_status(percent, f"Распознавание: прошло {int(elapsed)} сек.")
                        last_percent = percent
                    
                    time.sleep(5)  # Проверяем каждые 5 секунд
            
            response = operation.result(timeout=300)  # Увеличиваем таймаут для больших файлов
        else:
            # Для локальных файлов определяем метод по длительности
            # Примерная оценка для 16кГц, 16бит, моно
            audio_duration_seconds = len(content) / 32000 if 'content' in locals() else 60
            
            if audio_duration_seconds > 60:
                update_status(50, f"Запуск асинхронного распознавания для длинного аудио ({audio_duration_seconds:.1f} сек.)")
                operation = client.long_running_recognize(config=config, audio=audio)
                
                update_status(52, "Ожидание завершения распознавания...")
                start_time = time.time()
                done = False
                last_percent = 52
                
                while not done:
                    if operation.done():
                        done = True
                        update_status(90, "Распознавание завершено")
                    else:
                        elapsed = time.time() - start_time
                        # от 52% до 89%
                        percent = 52 + min(int((elapsed / audio_duration_seconds) * 38), 37)
                        if percent > last_percent:
                            update_status(percent, f"Распознавание: прошло {int(elapsed)} сек.")
                            last_percent = percent
                        
                        time.sleep(2)  # Проверяем каждые 2 секунды
                
                response = operation.result(timeout=180)  # Увеличиваем таймаут
            else:
                update_status(50, "Запуск синхронного распознавания для короткого аудио")
                response = client.recognize(config=config, audio=audio)
                update_status(90, "Распознавание завершено")
        
        # Проверяем, есть ли результаты распознавания
        if not response.results:
            update_status(95, "Предупреждение: речь не распознана")
            print("Предупреждение: API не вернул результатов распознавания")
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
        if file_size > 10 * 1024 * 1024 and 'gcs_uri' in locals():
            update_status(100, f"Аудиофайл сохранен в Cloud Storage: {gcs_uri}")
        
        # Удаляем временный конвертированный файл, если он создавался
        if prepared_file_path != file_path and os.path.exists(prepared_file_path):
            try:
                os.remove(prepared_file_path)
            except Exception as e:
                print(f"Не удалось удалить временный файл: {e}")

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
            min(10 + int(d['downloaded_percent'] * 0.3), 40), 
            f"Загрузка видео: {d['downloaded_percent']:.1f}%"
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

def save_transcript_to_session(session_id, transcript, docx_path, with_timestamps=False, video_info=None):
    """Сохранение транскрипции в сессию"""
    # Формируем уникальный URL для доступа к сессии
    share_url = f"/share/{session_id}"
    
    sessions[session_id] = {
        'created_at': datetime.datetime.now().timestamp(),
        'transcript': transcript,
        'docx_path': docx_path,
        'with_timestamps': with_timestamps,
        'video_info': video_info,
        'share_url': share_url
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
            docx_path=session_data['docx_path']
        )
    return render_template('error.html', message="Сессия не найдена или истекла")

@app.route('/task_status/<task_id>', methods=['GET'])
def get_task_status(task_id):
    """Получение статуса задачи по ID"""
    if task_id in task_status:
        return jsonify(task_status[task_id])
    return jsonify({'status': 'unknown', 'percent': 0, 'message': 'Задача не найдена'})

def process_audio_file(file_path, enable_timestamps, task_id):
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
        
        # Запускаем транскрибирование
        transcript = transcribe_audio(file_path, enable_timestamps=enable_timestamps, status_callback=update_status)
        
        # Генерируем ID сессии
        session_id = generate_session_id()
        
        # Создание DOCX файла
        docx_path = create_docx(transcript, os.path.splitext(os.path.basename(file_path))[0], with_timestamps=enable_timestamps)
        
        # Сохраняем транскрипцию в сессию
        share_url = save_transcript_to_session(session_id, transcript, os.path.basename(docx_path), enable_timestamps)
        
        # Финальное обновление статуса
        task_status[task_id] = {
            'status': 'complete',
            'percent': 100,
            'message': 'Транскрипция завершена',
            'transcript': transcript,
            'docx_path': os.path.basename(docx_path),
            'with_timestamps': enable_timestamps,
            'session_id': session_id,
            'share_url': share_url
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

def process_youtube_link(url, enable_timestamps, task_id):
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
        
        # Запускаем транскрибирование
        transcript = transcribe_audio(audio_path, enable_timestamps=enable_timestamps, status_callback=update_status)
        
        # Генерируем ID сессии
        session_id = generate_session_id()
        
        # Создание DOCX файла
        docx_path = create_docx(transcript, f"link_{uuid.uuid4()}", with_timestamps=enable_timestamps, video_info=video_info)
        
        # Сохраняем транскрипцию в сессию
        share_url = save_transcript_to_session(session_id, transcript, os.path.basename(docx_path), enable_timestamps, video_info)
        
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
            'share_url': share_url
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
        
        # Запускаем обработку в отдельном потоке
        threading.Thread(target=process_audio_file, args=(file_path, enable_timestamps, task_id)).start()
        
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
    
    # Запускаем обработку в отдельном потоке
    threading.Thread(target=process_audio_file, args=(file_path, enable_timestamps, task_id)).start()
    
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
    
    # Создаем ID задачи
    task_id = generate_task_id()
    
    # Инициализируем статус задачи
    task_status[task_id] = {
        'status': 'preparing',
        'percent': 0,
        'message': 'Подготовка к загрузке видео'
    }
    
    # Запускаем обработку в отдельном потоке
    threading.Thread(target=process_youtube_link, args=(url, enable_timestamps, task_id)).start()
    
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

# Добавьте в конец файла app.py перед if __name__ == '__main__':

@app.route('/api/analyze', methods=['POST'])
def analyze_transcript():
    """API для анализа транскрипции"""
    data = request.json
    
    if not data or 'transcript' not in data:
        return jsonify({'error': 'Транскрипция не найдена в запросе'}), 400
    
    transcript = data['transcript']
    with_timestamps = data.get('with_timestamps', False)
    
    try:
        # Анализ текста
        result = {}
        
        if with_timestamps and isinstance(transcript, list):
            # Статистика по говорящим
            speakers = {}
            word_frequencies = {}
            sentence_lengths = []
            total_words = 0
            
            for segment in transcript:
                speaker = segment['speaker']
                text = segment['text']
                
                # Разбиваем текст на слова
                words = re.findall(r'\b[а-яА-Яa-zA-Z]+\b', text.lower())
                sentences = re.split(r'[.!?]+', text)
                
                # Подсчет для говорящего
                if speaker not in speakers:
                    speakers[speaker] = {
                        'word_count': 0,
                        'sentence_count': 0,
                        'total_time': 0,
                        'avg_words_per_sentence': 0
                    }
                
                speakers[speaker]['word_count'] += len(words)
                speakers[speaker]['sentence_count'] += len(sentences)
                
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
            
            # Расчет средних значений
            for speaker, stats in speakers.items():
                if stats['sentence_count'] > 0:
                    stats['avg_words_per_sentence'] = stats['word_count'] / stats['sentence_count']
            
            # Сортируем частоты слов
            sorted_words = sorted(word_frequencies.items(), key=lambda x: x[1], reverse=True)
            top_words = sorted_words[:50]
            
            # Формируем результат
            result = {
                'speakers': speakers,
                'top_words': dict(top_words),
                'total_words': total_words,
                'avg_sentence_length': sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0,
                'sentence_count': len(sentence_lengths),
                'word_variety': len(word_frequencies) / total_words if total_words > 0 else 0
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
            top_words = sorted_words[:50]
            
            # Длина предложений
            sentence_lengths = []
            for sentence in sentences:
                if sentence.strip():
                    words_in_sentence = len(re.findall(r'\b[а-яА-Яa-zA-Z]+\b', sentence.lower()))
                    if words_in_sentence > 0:
                        sentence_lengths.append(words_in_sentence)
            
            # Формируем результат
            result = {
                'top_words': dict(top_words),
                'total_words': len(words),
                'avg_sentence_length': sum(sentence_lengths) / len(sentence_lengths) if sentence_lengths else 0,
                'sentence_count': len(sentence_lengths),
                'word_variety': len(word_frequencies) / len(words) if words else 0
            }
        
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