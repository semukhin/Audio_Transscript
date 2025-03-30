document.addEventListener('DOMContentLoaded', function() {
    // Переменные для хранения текущего состояния
    let currentTab = 'upload';
    let recordedBlob = null;
    let mediaRecorder = null;
    let recordingTimer = null;
    let recordingStartTime = 0;
    let audioContext = null;
    let analyser = null;
    let isRecording = false;
    let docxPath = null;
    
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
    const transcribeLinkButton = document.getElementById('transcribe-link');
    const progressContainer = document.getElementById('progress-container');
    const progressBar = document.getElementById('progress-bar');
    const progressStatus = document.getElementById('progress-status');
    const resultsContainer = document.getElementById('results-container');
    const transcriptContent = document.getElementById('transcript-content');
    const copyTranscriptButton = document.getElementById('copy-transcript');
    const downloadDocxButton = document.getElementById('download-docx');
    const visualizer = document.getElementById('visualizer');
    
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
        if (!fileType.startsWith('audio/')) {
            showToast('Пожалуйста, выберите аудиофайл', 'error');
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
        
        uploadFile(formData);
    });
    
    function uploadFile(formData) {
        showProgress('Подготовка к загрузке...', 0);
        
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
                trackTaskProgress(data.task_id);
            } else {
                // Если сразу получили результат (для обратной совместимости)
                updateProgress(100, 'Транскрипция завершена');
                showResults(data.transcript, data.with_timestamps);
                docxPath = data.docx_path;
                
                setTimeout(() => {
                    hideProgress();
                }, 1000);
            }
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
                    
                    if (status.status === 'complete') {
                        // Задача завершена, показываем результаты
                        clearInterval(statusInterval);
                        showResults(status.transcript, status.with_timestamps);
                        docxPath = status.docx_path;
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
            
            canvasCtx.fillStyle = '#f8f9fa';
            canvasCtx.fillRect(0, 0, width, height);
            
            const barWidth = width / bufferLength * 2.5;
            let x = 0;
            
            for (let i = 0; i < bufferLength; i++) {
                const barHeight = dataArray[i] / 255 * height;
                
                canvasCtx.fillStyle = `rgb(${dataArray[i] + 100}, 50, 230)`;
                canvasCtx.fillRect(x, height - barHeight, barWidth, barHeight);
                
                x += barWidth + 1;
            }
        }
        
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
        
        uploadFile(formData);
    });
    
    // Транскрибирование по ссылке
    transcribeLinkButton.addEventListener('click', () => {
        const link = videoLink.value.trim();
        
        if (!link) {
            showToast('Пожалуйста, введите ссылку', 'error');
            return;
        }
        
        showProgress('Подготовка к загрузке видео...', 0);
        
        fetch('/link', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                url: link,
                timestamps: linkTimestampsCheckbox.checked
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
                trackTaskProgress(data.task_id);
            } else {
                // Обратная совместимость
                updateProgress(100, 'Транскрипция завершена');
                showResults(data.transcript, data.with_timestamps);
                docxPath = data.docx_path;
                
                setTimeout(() => {
                    hideProgress();
                }, 1000);
            }
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
    function showResults(transcript, withTimestamps) {
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
        } else {
            // Обычный текст без таймингов
            transcriptContent.textContent = transcript;
        }
        
        resultsContainer.style.display = 'block';
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
});