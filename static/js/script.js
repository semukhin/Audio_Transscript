document.addEventListener('DOMContentLoaded', function() {
    // Переменные для хранения текущего состояния
    let currentTab = 'upload';
    let recordedBlob = null;
    let mediaRecorder = null;
    let recordingTimer = null;
    let recordingStartTime = 0;
    let audioContext = null;
    let analyser = null;
    let audioLevelInterval = null;
    let isRecording = false;
    let docxPath = null;
    let videoInfo = null;
    let currentTaskId = null;
    let videoLinkVerified = false;
    let currentSessionId = null;
    
    // Элементы DOM
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabPanes = document.querySelectorAll('.tab-pane');
    const dropArea = document.getElementById('drop-area');
    const fileInput = document.getElementById('file-input');
    const browseButton = document.getElementById('browse-button');
    const fileInfo = document.getElementById('file-info');
    const fileName = document.getElementById('file-name');
    const uploadButton = document.getElementById('upload-button');
    const timestampsCheckbox = document.getElementById('timestamps-checkbox');
    const recordTimestampsCheckbox = document.getElementById('record-timestamps-checkbox');
    const linkTimestampsCheckbox = document.getElementById('link-timestamps-checkbox');
    const startRecordButton = document.getElementById('start-record');
    const stopRecordButton = document.getElementById('stop-record');
    const recordTimer = document.getElementById('record-timer');
    const recordPreview = document.getElementById('record-preview');
    const audioPreview = document.getElementById('audio-preview');
    const transcribeRecordButton = document.getElementById('transcribe-record');
    const videoLink = document.getElementById('video-link');
    const verifyLinkButton = document.getElementById('verify-link');
    const videoPreview = document.getElementById('video-preview');
    const videoTitle = document.getElementById('video-title');
    const videoAuthor = document.getElementById('video-author').querySelector('span');
    const videoDuration = document.getElementById('video-duration').querySelector('span');
    const videoThumbnail = document.getElementById('video-thumbnail');
    const transcribeLinkButton = document.getElementById('transcribe-link');
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const progressStatus = document.getElementById('progress-status');
    const progressSteps = document.getElementById('progress-steps');
    const cancelProcessButton = document.getElementById('cancel-process');
    const resultsContainer = document.getElementById('results-container');
    const transcriptContent = document.getElementById('transcript-content');
    const copyTranscriptButton = document.getElementById('copy-transcript');
    const downloadDocxButton = document.getElementById('download-docx');
    const shareTranscriptButton = document.getElementById('share-transcript');
    const newTranscriptionButton = document.getElementById('new-transcription');
    const searchTranscript = document.getElementById('search-transcript');
    const searchResults = document.getElementById('search-results');
    const searchPrev = document.getElementById('search-prev');
    const searchNext = document.getElementById('search-next');
    const speakerFilter = document.getElementById('speaker-filter');
    const visualizer = document.getElementById('visualizer');
    const levelBar = document.getElementById('level-bar');
    const shareModal = document.getElementById('share-modal');
    const closeShareModal = document.getElementById('close-share-modal');
    const shareLink = document.getElementById('share-link');
    const copyShareLink = document.getElementById('copy-share-link');
    const shareTelegram = document.getElementById('share-telegram');
    const shareWhatsApp = document.getElementById('share-whatsapp');
    const shareVK = document.getElementById('share-vk');
    const videoInfoResults = document.getElementById('video-info-results');
    const resultsVideoTitle = document.getElementById('results-video-title');
    const resultsVideoAuthor = document.getElementById('results-video-author').querySelector('span');
    const resultsVideoDuration = document.getElementById('results-video-duration').querySelector('span');
    const resultsVideoThumbnail = document.getElementById('results-video-thumbnail');
    const analyticsContainer = document.getElementById('analytics-container');
    const speakersStats = document.getElementById('speakers-stats');
    const wordCloud = document.getElementById('word-cloud');
    const themeToggle = document.getElementById('theme-toggle');
    const languageSelect = document.getElementById('language-select');
    const recordLanguageSelect = document.getElementById('record-language-select');
    const linkLanguageSelect = document.getElementById('link-language-select');
    
    // Функции для работы с выбором языка
    function saveSelectedLanguage(lang) {
        localStorage.setItem('preferredLanguage', lang);
        
        // Синхронизируем все селекторы языка
        if (languageSelect) languageSelect.value = lang;
        if (recordLanguageSelect) recordLanguageSelect.value = lang;
        if (linkLanguageSelect) linkLanguageSelect.value = lang;
    }

    function loadSelectedLanguage() {
        const savedLang = localStorage.getItem('preferredLanguage');
        if (savedLang) {
            if (languageSelect) languageSelect.value = savedLang;
            if (recordLanguageSelect) recordLanguageSelect.value = savedLang;
            if (linkLanguageSelect) linkLanguageSelect.value = savedLang;
        }
    }

    // Добавляем обработчики событий для селекторов языка
    if (languageSelect) {
        languageSelect.addEventListener('change', function() {
            saveSelectedLanguage(this.value);
        });
    }

    if (recordLanguageSelect) {
        recordLanguageSelect.addEventListener('change', function() {
            saveSelectedLanguage(this.value);
        });
    }

    if (linkLanguageSelect) {
        linkLanguageSelect.addEventListener('change', function() {
            saveSelectedLanguage(this.value);
        });
    }
    
    // Переключение темной/светлой темы
    themeToggle.addEventListener('click', function() {
        const body = document.body;
        const isDarkMode = body.classList.contains('dark-mode');
        
        if (isDarkMode) {
            body.classList.remove('dark-mode');
            body.classList.add('light-mode');
            themeToggle.innerHTML = '<i class="fas fa-moon"></i>';
            localStorage.setItem('darkMode', 'false');
        } else {
            body.classList.remove('light-mode');
            body.classList.add('dark-mode');
            themeToggle.innerHTML = '<i class="fas fa-sun"></i>';
            localStorage.setItem('darkMode', 'true');
        }
    });
    
    // Проверяем сохраненные настройки темы
    const savedDarkMode = localStorage.getItem('darkMode') === 'true';
    if (savedDarkMode) {
        document.body.classList.remove('light-mode');
        document.body.classList.add('dark-mode');
        themeToggle.innerHTML = '<i class="fas fa-sun"></i>';
    }
    
    // Переключение вкладок
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            if (isRecording) {
                showToast('Пожалуйста, остановите запись перед переключением вкладки', 'error');
                return;
            }
            
            tabButtons.forEach(btn => btn.classList.remove('active'));
            tabPanes.forEach(pane => pane.classList.remove('active'));
            
            button.classList.add('active');
            const tabId = button.getAttribute('data-tab');
            document.getElementById(tabId).classList.add('active');
            currentTab = tabId;
            
            // Сохраняем состояние сессии при переключении вкладок
            saveSessionState();
        });
    });
    
    // Обработка перетаскивания и выбора файла
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, preventDefaults, false);
    });
    
    function preventDefaults(e) {
        e.preventDefault();
        e.stopPropagation();
    }
    
    ['dragenter', 'dragover'].forEach(eventName => {
        dropArea.addEventListener(eventName, highlight, false);
    });
    
    ['dragleave', 'drop'].forEach(eventName => {
        dropArea.addEventListener(eventName, unhighlight, false);
    });
    
    function highlight() {
        dropArea.classList.add('drag-over');
    }
    
    function unhighlight() {
        dropArea.classList.remove('drag-over');
    }
    
    dropArea.addEventListener('drop', handleDrop, false);
    
    function handleDrop(e) {
        const dt = e.dataTransfer;
        const files = dt.files;
        
        if (files.length > 0) {
            handleFiles(files);
        }
    }
    
    browseButton.addEventListener('click', () => {
        fileInput.click();
    });
    
    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) {
            handleFiles(fileInput.files);
        }
    });
    
    function handleFiles(files) {
        const file = files[0];
        const fileType = file.type;
        
        // Проверка типа файла
        if (!fileType.startsWith('audio/') && !fileType.startsWith('video/')) {
            showToast('Пожалуйста, выберите аудио или видео файл', 'error');
            return;
        }
        
        // Проверка размера файла (максимум 100 МБ)
        if (file.size > 100 * 1024 * 1024) {
            showToast('Размер файла не должен превышать 100 МБ', 'error');
            return;
        }
        
        fileName.textContent = file.name;
        fileInfo.style.display = 'block';
    }
    
    // Загрузка файла и отслеживание статуса
    uploadButton.addEventListener('click', () => {
        if (fileInput.files.length === 0) {
            showToast('Пожалуйста, выберите файл', 'error');
            return;
        }
        
        const file = fileInput.files[0];
        const formData = new FormData();
        formData.append('file', file);
        formData.append('timestamps', timestampsCheckbox.checked);
        // Добавляем выбранный язык
        formData.append('language', languageSelect ? languageSelect.value : 'ru-RU');
        
        uploadFile(formData);
    });
    
    function uploadFile(formData) {
        showProgress('Подготовка к загрузке...', 0);
        updateProgressStep('prepare');
        
        fetch('/upload', {
            method: 'POST',
            body: formData
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Ошибка при загрузке файла');
            }
            return response.json();
        })
        .then(data => {
            if (data.task_id) {
                // Если получили ID задачи, начинаем отслеживать прогресс
                currentTaskId = data.task_id;
                trackTaskProgress(data.task_id);
            } else {
                // Если сразу получили результат (для обратной совместимости)
                updateProgress(100, 'Транскрипция завершена');
                showResults(data.transcript, data.with_timestamps, data.video_info);
                docxPath = data.docx_path;
                currentSessionId = data.session_id;
                
                setTimeout(() => {
                    hideProgress();
                }, 1000);
            }
            
            // Сохраняем состояние сессии
            saveSessionState();
        })
        .catch(error => {
            hideProgress();
            showToast(error.message, 'error');
        });
    }
    
    // Функция для отслеживания прогресса задачи
    function trackTaskProgress(taskId) {
        const statusInterval = setInterval(() => {
            fetch(`/task_status/${taskId}`)
                .then(response => response.json())
                .then(status => {
                    updateProgress(status.percent, status.message);
                    
                    // Обновление шагов прогресса
                    if (status.percent < 20) {
                        updateProgressStep('prepare');
                    } else if (status.percent < 40) {
                        updateProgressStep('analyze');
                    } else if (status.percent < 90) {
                        updateProgressStep('transcribe');
                    } else {
                        updateProgressStep('format');
                    }
                    
                    if (status.status === 'complete') {
                        // Задача завершена, показываем результаты
                        clearInterval(statusInterval);
                        showResults(status.transcript, status.with_timestamps, status.video_info);
                        docxPath = status.docx_path;
                        currentSessionId = status.session_id;
                        
                        // Сохраняем URL для общего доступа
                        if (status.share_url) {
                            shareLink.value = window.location.origin + status.share_url;
                        }
                        
                        // Сохраняем состояние сессии
                        saveSessionState();
                    } else if (status.status === 'error') {
                        // Ошибка при выполнении задачи
                        clearInterval(statusInterval);
                        hideProgress();
                        showToast(status.message, 'error');
                    }
                })
                .catch(error => {
                    console.error('Ошибка при получении статуса:', error);
                    clearInterval(statusInterval);
                    hideProgress();
                    showToast('Потеряна связь с сервером', 'error');
                });
        }, 1000); // Проверяем статус каждую секунду
    }
    
    // Функция для обновления шага прогресса
    function updateProgressStep(step) {
        const steps = ['prepare', 'analyze', 'transcribe', 'format'];
        const currentStepIndex = steps.indexOf(step);
        
        // Сначала сбрасываем все шаги
        progressSteps.querySelectorAll('.step').forEach(stepEl => {
            stepEl.classList.remove('active', 'completed');
        });
        
        // Затем устанавливаем текущий шаг и завершенные шаги
        for (let i = 0; i <= currentStepIndex; i++) {
            const stepEl = progressSteps.querySelector(`.step[data-step="${steps[i]}"]`);
            if (i === currentStepIndex) {
                stepEl.classList.add('active');
            } else {
                stepEl.classList.add('completed');
            }
        }
    }
    
    // Прерывание процесса
    cancelProcessButton.addEventListener('click', () => {
        if (confirm('Вы уверены, что хотите отменить текущую транскрипцию?')) {
            hideProgress();
            showToast('Транскрипция отменена', 'error');
            currentTaskId = null;
        }
    });
    
    // Запись аудио
    startRecordButton.addEventListener('click', startRecording);
    stopRecordButton.addEventListener('click', stopRecording);
    
    function startRecording() {
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            navigator.mediaDevices.getUserMedia({ audio: true })
                .then(stream => {
                    isRecording = true;
                    startRecordButton.style.display = 'none';
                    stopRecordButton.style.display = 'inline-block';
                    
                    // Настройка MediaRecorder
                    mediaRecorder = new MediaRecorder(stream);
                    const chunks = [];
                    
                    mediaRecorder.addEventListener('dataavailable', e => {
                        chunks.push(e.data);
                    });
                    
                    mediaRecorder.addEventListener('stop', () => {
                        const blob = new Blob(chunks, { type: 'audio/wav' });
                        recordedBlob = blob;
                        const audioURL = URL.createObjectURL(blob);
                        audioPreview.src = audioURL;
                        recordPreview.style.display = 'block';
                        
                        // Остановка визуализации
                        if (audioContext) {
                            audioContext.close().then(() => {
                                audioContext = null;
                                analyser = null;
                            });
                        }
                        
                        // Остановка отслеживания уровня аудио
                        if (audioLevelInterval) {
                            clearInterval(audioLevelInterval);
                        }
                        
                        // Сохраняем состояние сессии
                        saveSessionState();
                    });
                    
                    // Начало записи
                    mediaRecorder.start();
                    
                    // Запуск таймера
                    recordingStartTime = Date.now();
                    recordingTimer = setInterval(updateRecordingTime, 1000);
                    
                    // Настройка визуализации
                    setupAudioVisualization(stream);
                })
                .catch(error => {
                    showToast('Ошибка доступа к микрофону: ' + error.message, 'error');
                });
        } else {
            showToast('Ваш браузер не поддерживает запись аудио', 'error');
        }
    }
    
    function stopRecording() {
        if (mediaRecorder && isRecording) {
            mediaRecorder.stop();
            isRecording = false;
            clearInterval(recordingTimer);
            stopRecordButton.style.display = 'none';
            startRecordButton.style.display = 'inline-block';
        }
    }
    
    function updateRecordingTime() {
        const elapsedSeconds = Math.floor((Date.now() - recordingStartTime) / 1000);
        const minutes = Math.floor(elapsedSeconds / 60).toString().padStart(2, '0');
        const seconds = (elapsedSeconds % 60).toString().padStart(2, '0');
        recordTimer.textContent = `${minutes}:${seconds}`;
    }
    
    function setupAudioVisualization(stream) {
        if (!visualizer) return;
        
        const canvasCtx = visualizer.getContext('2d');
        const width = visualizer.width;
        const height = visualizer.height;
        
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioContext.createAnalyser();
        const source = audioContext.createMediaStreamSource(stream);
        source.connect(analyser);
        
        analyser.fftSize = 256;
        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        
        canvasCtx.clearRect(0, 0, width, height);
        
        function draw() {
            if (!isRecording) return;
            
            requestAnimationFrame(draw);
            analyser.getByteFrequencyData(dataArray);
            
            canvasCtx.fillStyle = getComputedStyle(document.body).getPropertyValue('--highlight-bg');
            canvasCtx.fillRect(0, 0, width, height);
            
            const barWidth = width / bufferLength * 2.5;
            let x = 0;
            
            for (let i = 0; i < bufferLength; i++) {
                const barHeight = dataArray[i] / 255 * height;
                
                canvasCtx.fillStyle = getComputedStyle(document.body).getPropertyValue('--primary-color');
                canvasCtx.fillRect(x, height - barHeight, barWidth, barHeight);
                
                x += barWidth + 1;
            }
        }
        
        // Отслеживание общего уровня аудио для индикатора
        audioLevelInterval = setInterval(() => {
            if (!isRecording || !analyser) return;
            
            analyser.getByteFrequencyData(dataArray);
            
            // Вычисляем средний уровень сигнала
            let sum = 0;
            for (let i = 0; i < bufferLength; i++) {
                sum += dataArray[i];
            }
            const avg = sum / bufferLength;
            const level = Math.min(100, Math.round(avg / 255 * 100));
            
            // Обновляем индикатор уровня
            levelBar.style.width = `${level}%`;
            
            // Изменяем цвет в зависимости от уровня
            if (level < 30) {
                levelBar.style.backgroundColor = '#28a745'; // зеленый - тихо
            } else if (level < 70) {
                levelBar.style.backgroundColor = '#ffc107'; // желтый - нормально
            } else {
                levelBar.style.backgroundColor = '#dc3545'; // красный - громко
            }
        }, 100);
        
        draw();
    }
    
    // Транскрибирование записанного аудио
    transcribeRecordButton.addEventListener('click', () => {
        if (!recordedBlob) {
            showToast('Запись не найдена', 'error');
            return;
        }
        
        const formData = new FormData();
        formData.append('audio_data', recordedBlob, 'recording.wav');
        formData.append('timestamps', recordTimestampsCheckbox.checked);
        // Добавляем выбранный язык
        formData.append('language', recordLanguageSelect ? recordLanguageSelect.value : 'ru-RU');
        
        uploadFile(formData);
    });
    
    // Проверка ссылки на видео
    verifyLinkButton.addEventListener('click', verifyVideoLink);
    videoLink.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            verifyVideoLink();
        }
    });
    
    function verifyVideoLink() {
        const link = videoLink.value.trim();
        
        if (!link) {
            showToast('Пожалуйста, введите ссылку', 'error');
            return;
        }
        
        videoPreview.style.display = 'none';
        videoLinkVerified = false;
        
        // Отправляем запрос для проверки ссылки
        fetch('/api/verify_link', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ url: link })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success' && data.video_info) {
                // Отображаем информацию о видео
                videoTitle.textContent = data.video_info.title;
                videoAuthor.textContent = data.video_info.uploader;
                
                // Форматируем длительность
                if (data.video_info.duration) {
                    const minutes = Math.floor(data.video_info.duration / 60);
                    const seconds = data.video_info.duration % 60;
                    videoDuration.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
                } else {
                    videoDuration.textContent = 'Неизвестно';
                }
                
                // Устанавливаем миниатюру
                if (data.video_info.thumbnail) {
                    videoThumbnail.src = data.video_info.thumbnail;
                } else {
                    videoThumbnail.src = '/static/img/video-placeholder.png';
                }
                
                videoPreview.style.display = 'block';
                videoLinkVerified = true;
                videoInfo = data.video_info;
                showToast('Ссылка проверена успешно', 'success');
            } else {
                showToast(data.message || 'Не удалось получить информацию по ссылке', 'error');
            }
        })
        .catch(error => {
            showToast('Ошибка при проверке ссылки', 'error');
            console.error(error);
        });
    }
    
    // Транскрибирование по ссылке
    transcribeLinkButton.addEventListener('click', () => {
        const link = videoLink.value.trim();
        
        if (!link) {
            showToast('Пожалуйста, введите ссылку', 'error');
            return;
        }
        
        showProgress('Подготовка к загрузке видео...', 0);
        updateProgressStep('prepare');
        
        fetch('/link', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                url: link,
                timestamps: linkTimestampsCheckbox.checked,
                language: linkLanguageSelect ? linkLanguageSelect.value : 'ru-RU'
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Ошибка при обработке ссылки');
            }
            return response.json();
        })
        .then(data => {
            if (data.task_id) {
                // Если получили ID задачи, начинаем отслеживать прогресс
                currentTaskId = data.task_id;
                trackTaskProgress(data.task_id);
            } else {
                // Обратная совместимость
                updateProgress(100, 'Транскрипция завершена');
                showResults(data.transcript, data.with_timestamps, data.video_info);
                docxPath = data.docx_path;
                currentSessionId = data.session_id;
                
                setTimeout(() => {
                    hideProgress();
                }, 1000);
            }
            
            // Сохраняем состояние сессии
            saveSessionState();
        })
        .catch(error => {
            hideProgress();
            showToast(error.message, 'error');
        });
    });
    
    // Копирование транскрипции
    copyTranscriptButton.addEventListener('click', () => {
        let text;
        
        // Проверяем, содержит ли транскрипция HTML-разметку
        if (transcriptContent.querySelector('.transcript-line')) {
            // Извлекаем текстовое содержимое, сохраняя структуру
            text = Array.from(transcriptContent.querySelectorAll('.transcript-line'))
                .map(line => {
                    const time = line.querySelector('.transcript-time')?.textContent || '';
                    const speaker = line.querySelector('.transcript-speaker')?.textContent || '';
                    const textContent = line.querySelector('.transcript-text')?.textContent || '';
                    return `[${time}] ${speaker} ${textContent}`;
                })
                .join('\n\n');
        } else {
            // Простой текст
            text = transcriptContent.textContent;
        }
        
        if (navigator.clipboard) {
            navigator.clipboard.writeText(text)
                .then(() => {
                    showToast('Текст скопирован в буфер обмена', 'success');
                })
                .catch(() => {
                    showToast('Не удалось скопировать текст', 'error');
                });
        } else {
            // Fallback для старых браузеров
            const textarea = document.createElement('textarea');
            textarea.value = text;
            document.body.appendChild(textarea);
            textarea.select();
            
            try {
                document.execCommand('copy');
                showToast('Текст скопирован в буфер обмена', 'success');
            } catch (err) {
                showToast('Не удалось скопировать текст', 'error');
            }
            
            document.body.removeChild(textarea);
        }
    });
    
    // Скачивание DOCX
    downloadDocxButton.addEventListener('click', () => {
        if (!docxPath) {
            showToast('Файл не найден', 'error');
            return;
        }
        
        window.location.href = '/download/' + docxPath;
    });
    
    // Поделиться транскрипцией
    shareTranscriptButton.addEventListener('click', () => {
        if (!currentSessionId) {
            showToast('Ошибка при создании ссылки для общего доступа', 'error');
            return;
        }
        
        // Установим ссылку для общего доступа
        const shareUrl = `${window.location.origin}/share/${currentSessionId}`;
        shareLink.value = shareUrl;
        
        // Настройка кнопок для социальных сетей
        if (shareTelegram) {
            shareTelegram.onclick = () => {
                window.open(`https://t.me/share/url?url=${encodeURIComponent(shareUrl)}&text=${encodeURIComponent('Транскрипция аудио')}`, '_blank');
            };
        }
        
        if (shareWhatsApp) {
            shareWhatsApp.onclick = () => {
                window.open(`https://wa.me/?text=${encodeURIComponent(shareUrl)}`, '_blank');
            };
        }
        
        if (shareVK) {
            shareVK.onclick = () => {
                window.open(`https://vk.com/share.php?url=${encodeURIComponent(shareUrl)}`, '_blank');
            };
        }
        
        // Показать модальное окно
        shareModal.classList.add('show');
    });
    
    // Закрытие модального окна
    if (closeShareModal) {
        closeShareModal.addEventListener('click', () => {
            shareModal.classList.remove('show');
        });
    }
    
    // Клик вне модального окна закрывает его
    window.addEventListener('click', (e) => {
        if (e.target === shareModal) {
            shareModal.classList.remove('show');
        }
    });
    
    // Копирование ссылки для общего доступа
    if (copyShareLink) {
        copyShareLink.addEventListener('click', () => {
            shareLink.select();
            
            if (navigator.clipboard) {
                navigator.clipboard.writeText(shareLink.value)
                    .then(() => {
                        showToast('Ссылка скопирована в буфер обмена', 'success');
                    })
                    .catch(() => {
                        showToast('Не удалось скопировать ссылку', 'error');
                    });
            } else {
try {
                    document.execCommand('copy');
                    showToast('Ссылка скопирована в буфер обмена', 'success');
                } catch (err) {
                    showToast('Не удалось скопировать ссылку', 'error');
                }
            }
        });
    }
    
    // Новая транскрипция
    newTranscriptionButton.addEventListener('click', () => {
        // Сбрасываем все формы и состояния
        fileInput.value = '';
        fileInfo.style.display = 'none';
        recordPreview.style.display = 'none';
        videoLink.value = '';
        videoPreview.style.display = 'none';
        videoLinkVerified = false;
        videoInfo = null;
        docxPath = null;
        currentTaskId = null;
        currentSessionId = null;
        
        // Сбрасываем интерфейс результатов
        resultsContainer.style.display = 'none';
        transcriptContent.innerHTML = '';
        videoInfoResults.style.display = 'none';
        analyticsContainer.style.display = 'none';
        
        // Возвращаемся на первую вкладку
        tabButtons[0].click();
        
        showToast('Готово для новой транскрипции', 'success');
        
        // Сбрасываем состояние сессии
        localStorage.removeItem('transcriptionSessionState');
    });
    
    // Поиск по тексту транскрипции
    let matchedNodes = [];
    let currentMatchIndex = -1;
    
    searchTranscript.addEventListener('input', function() {
        const searchTerm = this.value.trim().toLowerCase();
        
        // Сбрасываем предыдущие результаты поиска
        transcriptContent.querySelectorAll('.highlight').forEach(el => {
            const parent = el.parentNode;
            parent.replaceChild(document.createTextNode(el.textContent), el);
            parent.normalize();
        });
        
        matchedNodes = [];
        currentMatchIndex = -1;
        searchResults.textContent = '0/0';
        searchPrev.disabled = true;
        searchNext.disabled = true;
        
        if (searchTerm.length < 2) return;
        
        function searchInTextNodes(node) {
            if (node.nodeType === 3) { // Текстовый узел
                const text = node.textContent.toLowerCase();
                const index = text.indexOf(searchTerm);
                
                if (index >= 0) {
                    const range = document.createRange();
                    const spanNode = document.createElement('span');
                    spanNode.className = 'highlight';
                    spanNode.textContent = node.textContent.substring(index, index + searchTerm.length);
                    
                    range.setStart(node, index);
                    range.setEnd(node, index + searchTerm.length);
                    range.deleteContents();
                    range.insertNode(spanNode);
                    
                    matchedNodes.push(spanNode);
                    
                    // Продолжаем поиск в оставшейся части текста
                    if (spanNode.nextSibling) {
                        searchInTextNodes(spanNode.nextSibling);
                    }
                    
                    return;
                }
            } else if (node.nodeType === 1) { // Элемент
                Array.from(node.childNodes).forEach(child => {
                    searchInTextNodes(child);
                });
            }
        }
        
        searchInTextNodes(transcriptContent);
        
        if (matchedNodes.length > 0) {
            searchResults.textContent = `1/${matchedNodes.length}`;
            currentMatchIndex = 0;
            searchPrev.disabled = false;
            searchNext.disabled = false;
            highlightMatch(0);
        } else {
            searchResults.textContent = '0/0';
        }
    });
    
    function highlightMatch(index) {
        // Удаляем активную подсветку
        transcriptContent.querySelectorAll('.highlight.active').forEach(el => {
            el.classList.remove('active');
        });
        
        if (index >= 0 && index < matchedNodes.length) {
            const node = matchedNodes[index];
            node.classList.add('active');
            node.scrollIntoView({ behavior: 'smooth', block: 'center' });
            
            searchResults.textContent = `${index + 1}/${matchedNodes.length}`;
        }
    }
    
    searchNext.addEventListener('click', function() {
        if (matchedNodes.length === 0) return;
        
        currentMatchIndex = (currentMatchIndex + 1) % matchedNodes.length;
        highlightMatch(currentMatchIndex);
    });
    
    searchPrev.addEventListener('click', function() {
        if (matchedNodes.length === 0) return;
        
        currentMatchIndex = (currentMatchIndex - 1 + matchedNodes.length) % matchedNodes.length;
        highlightMatch(currentMatchIndex);
    });
    
    // Фильтрация по говорящим
    speakerFilter.addEventListener('change', function() {
        const selectedSpeaker = this.value;
        
        if (selectedSpeaker === 'all') {
            transcriptContent.querySelectorAll('.transcript-line').forEach(line => {
                line.style.display = '';
            });
        } else {
            transcriptContent.querySelectorAll('.transcript-line').forEach(line => {
                const speaker = line.querySelector('.transcript-speaker').textContent.replace(':', '').trim();
                line.style.display = (speaker === selectedSpeaker) ? '' : 'none';
            });
        }
    });
    
    // Функции для анализа транскрипции
    function generateAnalytics(transcript, withTimestamps) {
        if (!analyticsContainer) return;
        
        // Очищаем контейнеры
        speakersStats.innerHTML = '';
        wordCloud.innerHTML = '';
        
        if (withTimestamps && Array.isArray(transcript)) {
            // Статистика по говорящим
            const speakers = {};
            const allWords = {};
            let totalWords = 0;
            
            // Собираем статистику
            transcript.forEach(segment => {
                const speaker = segment.speaker;
                const text = segment.text;
                const words = text.split(/\s+/).filter(word => word.length > 0);
                
                // Подсчет слов для каждого говорящего
                if (!speakers[speaker]) {
                    speakers[speaker] = {
                        wordCount: 0,
                        segments: 0,
                        words: {}
                    };
                }
                
                speakers[speaker].wordCount += words.length;
                speakers[speaker].segments += 1;
                totalWords += words.length;
                
                // Подсчет отдельных слов
                words.forEach(word => {
                    // Нормализация слова
                    const normalizedWord = word.toLowerCase().replace(/[.,!?;:"'()\[\]{}]/g, '');
                    if (normalizedWord.length < 3) return; // Пропускаем короткие слова
                    
                    // Общая статистика слов
                    allWords[normalizedWord] = (allWords[normalizedWord] || 0) + 1;
                    
                    // Статистика слов по говорящим
                    speakers[speaker].words[normalizedWord] = (speakers[speaker].words[normalizedWord] || 0) + 1;
                });
            });
            
            // Отображение статистики по говорящим
            Object.keys(speakers).forEach(speaker => {
                const speakerData = speakers[speaker];
                const percentage = ((speakerData.wordCount / totalWords) * 100).toFixed(1);
                
                const speakerElement = document.createElement('div');
                speakerElement.className = 'speaker-stat';
                
                const speakerNameElement = document.createElement('div');
                speakerNameElement.className = 'speaker-name';
                speakerNameElement.innerHTML = `
                    <span>${speaker}</span>
                    <span>${speakerData.wordCount} слов (${percentage}%)</span>
                `;
                
                const speakerBarElement = document.createElement('div');
                speakerBarElement.className = 'speaker-bar';
                
                const speakerProgressElement = document.createElement('div');
                speakerProgressElement.className = 'speaker-progress';
                speakerProgressElement.style.width = `${percentage}%`;
                
                speakerBarElement.appendChild(speakerProgressElement);
                speakerElement.appendChild(speakerNameElement);
                speakerElement.appendChild(speakerBarElement);
                
                speakersStats.appendChild(speakerElement);
            });
            
            // Отображение облака слов
            // Сортируем слова по частоте и берем топ-20
            const sortedWords = Object.entries(allWords)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 20);
            
            // Создаем элементы для облака слов
            sortedWords.forEach(([word, count]) => {
                const size = Math.max(14, Math.min(24, 14 + Math.floor(count / 2)));
                
                const wordElement = document.createElement('span');
                wordElement.className = 'word-cloud-item';
                wordElement.textContent = word;
                wordElement.style.fontSize = `${size}px`;
                
                wordCloud.appendChild(wordElement);
            });
            
            analyticsContainer.style.display = 'block';
        } else {
            analyticsContainer.style.display = 'none';
        }
    }
    
    // Функции для отображения прогресса
    function showProgress(message, percent = 0) {
        progressStatus.textContent = message;
        progressBar.style.width = percent + '%';
        progressBar.setAttribute('data-percent', percent + '%');
        progressContainer.style.display = 'block';
        resultsContainer.style.display = 'none';
    }
    
    function updateProgress(percent, message) {
        progressBar.style.width = percent + '%';
        progressBar.setAttribute('data-percent', percent + '%');
        if (message) {
            progressStatus.textContent = message;
        }
    }
    
    function hideProgress() {
        progressContainer.style.display = 'none';
    }
    
    // Отображение результатов
    function showResults(transcript, withTimestamps, videoMetadata) {
        if (withTimestamps && Array.isArray(transcript)) {
            // Форматирование данных с таймингами
            transcriptContent.innerHTML = '';
            
            transcript.forEach(segment => {
                const lineDiv = document.createElement('div');
                lineDiv.className = 'transcript-line';
                
                const timeSpan = document.createElement('span');
                timeSpan.className = 'transcript-time';
                timeSpan.textContent = segment.start_time;
                
                const speakerSpan = document.createElement('span');
                speakerSpan.className = 'transcript-speaker';
                speakerSpan.textContent = segment.speaker + ':';
                
                const textSpan = document.createElement('span');
                textSpan.className = 'transcript-text';
                textSpan.textContent = segment.text;
                
                lineDiv.appendChild(timeSpan);
                lineDiv.appendChild(speakerSpan);
                lineDiv.appendChild(textSpan);
                
                transcriptContent.appendChild(lineDiv);
            });
            
            // Заполняем фильтр говорящих
            populateSpeakerFilter(transcript);
        } else {
            // Обычный текст без таймингов
            transcriptContent.textContent = transcript;
            
            // Скрываем фильтр говорящих
            speakerFilter.parentElement.style.display = 'none';
        }
        
        // Отображаем информацию о видео, если она есть
        if (videoMetadata) {
            videoInfoResults.style.display = 'block';
            resultsVideoTitle.textContent = videoMetadata.title;
            resultsVideoAuthor.textContent = videoMetadata.uploader;
            
            if (videoMetadata.duration) {
                const minutes = Math.floor(videoMetadata.duration / 60);
                const seconds = videoMetadata.duration % 60;
                resultsVideoDuration.textContent = `${minutes}:${seconds.toString().padStart(2, '0')}`;
            } else {
                resultsVideoDuration.textContent = 'Неизвестно';
            }
            
            if (videoMetadata.thumbnail) {
                resultsVideoThumbnail.src = videoMetadata.thumbnail;
            } else {
                resultsVideoThumbnail.src = '/static/img/video-placeholder.png';
            }
        } else {
            videoInfoResults.style.display = 'none';
        }
        
        // Генерируем аналитику
        generateAnalytics(transcript, withTimestamps);
        
        // Отображаем контейнер результатов
        resultsContainer.style.display = 'block';
        
        // Скрываем прогресс
        hideProgress();
        
        // Прокручиваем к результатам
        resultsContainer.scrollIntoView({ behavior: 'smooth' });
    }
    
    // Заполнение фильтра говорящих
    function populateSpeakerFilter(transcript) {
        // Очищаем текущие опции, кроме "Все участники"
        Array.from(speakerFilter.options).forEach(option => {
            if (option.value !== 'all') {
                speakerFilter.removeChild(option);
            }
        });
        
        // Получаем всех уникальных говорящих
        const speakers = new Set();
        transcript.forEach(segment => {
            speakers.add(segment.speaker);
        });
        
        // Добавляем опции для каждого говорящего
        speakers.forEach(speaker => {
            const option = document.createElement('option');
            option.value = speaker;
            option.textContent = speaker;
            speakerFilter.appendChild(option);
        });
        
        // Отображаем фильтр, если есть несколько говорящих
        speakerFilter.parentElement.style.display = speakers.size > 1 ? '' : 'none';
    }
    
    // Функция для отображения уведомлений
    function showToast(message, type = 'success') {
        const toast = document.getElementById('toast');
        toast.textContent = message;
        toast.className = 'toast ' + type;
        toast.classList.add('show');
        
        setTimeout(() => {
            toast.classList.remove('show');
        }, 3000);
    }
    
    // Функции для сохранения и восстановления состояния сессии
    function saveSessionState() {
        const currentState = {
            currentTab: currentTab,
            currentTaskId: currentTaskId,
            docxPath: docxPath,
            videoInfo: videoInfo,
            currentSessionId: currentSessionId,
            transcriptHTML: transcriptContent.innerHTML,
            resultsVisible: resultsContainer.style.display !== 'none',
            timestamp: Date.now(),
            language: (
                (currentTab === 'upload' && languageSelect) ? languageSelect.value : 
                (currentTab === 'record' && recordLanguageSelect) ? recordLanguageSelect.value : 
                (currentTab === 'link' && linkLanguageSelect) ? linkLanguageSelect.value : 
                'ru-RU'
            )
        };
        
        localStorage.setItem('transcriptionSessionState', JSON.stringify(currentState));
    }
    
    function restoreSessionState() {
        const savedStateJson = localStorage.getItem('transcriptionSessionState');
        if (!savedStateJson) return;
        
        try {
            const savedState = JSON.parse(savedStateJson);
            
            // Проверяем время сохранения (не более 24 часов)
            const now = Date.now();
            if (now - savedState.timestamp > 24 * 60 * 60 * 1000) {
                localStorage.removeItem('transcriptionSessionState');
                return;
            }
            
            // Восстанавливаем выбранный язык
            if (savedState.language) {
                saveSelectedLanguage(savedState.language);
            }
            
            // Восстанавливаем состояние вкладки
            if (savedState.currentTab) {
                const tabButton = document.querySelector(`.tab-button[data-tab="${savedState.currentTab}"]`);
                if (tabButton) tabButton.click();
            }
            
            // Восстанавливаем ID задачи и продолжаем отслеживание, если необходимо
            if (savedState.currentTaskId) {
                currentTaskId = savedState.currentTaskId;
                fetch(`/task_status/${currentTaskId}`)
                    .then(response => response.json())
                    .then(status => {
                        if (status.status === 'transcribing') {
                            // Задача все еще выполняется
                            showProgress(status.message, status.percent);
                            trackTaskProgress(currentTaskId);
                        } else if (status.status === 'complete') {
                            // Задача завершена, показываем результаты
                            if (savedState.resultsVisible && savedState.transcriptHTML) {
                                transcriptContent.innerHTML = savedState.transcriptHTML;
                                resultsContainer.style.display = 'block';
                            }
                        }
                    })
                    .catch(error => {
                        console.error('Ошибка при восстановлении статуса задачи:', error);
                    });
            }
            
            // Восстанавливаем путь к DOCX
            if (savedState.docxPath) {
                docxPath = savedState.docxPath;
            }
            
            // Восстанавливаем информацию о видео
            if (savedState.videoInfo) {
                videoInfo = savedState.videoInfo;
            }
            
            // Восстанавливаем ID сессии
            if (savedState.currentSessionId) {
                currentSessionId = savedState.currentSessionId;
            }
            
            // Восстанавливаем результаты, если они были видимы
            if (savedState.resultsVisible && savedState.transcriptHTML) {
                transcriptContent.innerHTML = savedState.transcriptHTML;
                resultsContainer.style.display = 'block';
                
                // Восстанавливаем фильтр говорящих
                if (transcriptContent.querySelector('.transcript-line')) {
                    const transcript = Array.from(transcriptContent.querySelectorAll('.transcript-line')).map(line => {
                        return {
                            speaker: line.querySelector('.transcript-speaker').textContent.replace(':', '').trim(),
                            text: line.querySelector('.transcript-text').textContent,
                            start_time: line.querySelector('.transcript-time').textContent
                        };
                    });
                    
                    populateSpeakerFilter(transcript);
                    generateAnalytics(transcript, true);
                }
            }
        } catch (error) {
            console.error('Ошибка при восстановлении состояния сессии:', error);
            localStorage.removeItem('transcriptionSessionState');
        }
    }
    
    // Загрузка сохраненного языка при инициализации
    loadSelectedLanguage();
    
    // Восстанавливаем состояние сессии при загрузке страницы
    restoreSessionState();
    
    // Сохраняем состояние перед закрытием страницы
    window.addEventListener('beforeunload', saveSessionState);
});