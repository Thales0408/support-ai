const startBtn =
    document.getElementById('start')

const statusDiv =
    document.getElementById('status')

let recorder = null

let chunks = []

let screenStream = null

let micStream = null

let inicioLigacao = null

// =====================================
// FORMATAR TEMPO
// =====================================

function formatarTempo(ms) {

    const totalSegundos =
        Math.floor(ms / 1000)

    const minutos =
        Math.floor(totalSegundos / 60)

    const segundos =
        totalSegundos % 60

    return `${String(minutos).padStart(2, '0')}m ${String(segundos).padStart(2, '0')}s`
}

// =====================================
// CLICK
// =====================================

startBtn.onclick = async () => {

    // =================================
    // PARAR
    // =================================

    if (
        recorder &&
        recorder.state === 'recording'
    ) {

        recorder.stop()

        screenStream
            .getTracks()
            .forEach(t => t.stop())

        micStream
            .getTracks()
            .forEach(t => t.stop())

        startBtn.innerText =
            'Iniciar Gravação'

        const fimLigacao =
            Date.now()

        const duracao =
            fimLigacao - inicioLigacao

        statusDiv.innerText =
            'Ligação finalizada • TMA: ' +
            formatarTempo(duracao)

        return
    }

    try {

        statusDiv.innerText =
            'Escolha a aba do 55PBX'

        // =================================
        // INICIO
        // =================================

        inicioLigacao =
            Date.now()

        // =================================
        // ABA
        // =================================

        screenStream =
            await navigator
                .mediaDevices
                .getDisplayMedia({

                    video: true,
                    audio: true

                })

        // =================================
        // MICROFONE
        // =================================

        micStream =
            await navigator
                .mediaDevices
                .getUserMedia({

                    audio: true

                })

        // =================================
        // AUDIO CONTEXT
        // =================================

        const audioContext =
            new AudioContext()

        const destination =
            audioContext
                .createMediaStreamDestination()

        // =================================
        // AUDIO ABA
        // =================================

        if (
            screenStream
                .getAudioTracks()
                .length > 0
        ) {

            const systemSource =
                audioContext
                    .createMediaStreamSource(

                        new MediaStream([
                            screenStream
                                .getAudioTracks()[0]
                        ])

                    )

            systemSource.connect(
                destination
            )
        }

        // =================================
        // MICROFONE
        // =================================

        if (
            micStream
                .getAudioTracks()
                .length > 0
        ) {

            const micSource =
                audioContext
                    .createMediaStreamSource(

                        new MediaStream([
                            micStream
                                .getAudioTracks()[0]
                        ])

                    )

            micSource.connect(
                destination
            )
        }

        // =================================
        // STREAM FINAL
        // =================================

        const finalStream =
            destination.stream

        recorder =
            new MediaRecorder(
                finalStream
            )

        chunks = []

        recorder.ondataavailable = e => {

            if (e.data.size > 0) {

                chunks.push(e.data)
            }
        }

        // =================================
        // STOP
        // =================================

        recorder.onstop = async () => {

            statusDiv.innerText =
                'Transcrevendo...'

            const blob =
                new Blob(chunks, {

                    type: 'audio/webm'

                })

            const formData =
                new FormData()

            formData.append(
                'audio',
                blob,
                'gravacao.webm'
            )

            try {

                const response =
                    await fetch(

                        'http://127.0.0.1:8080/transcrever',

                        {
                            method: 'POST',
                            body: formData
                        }

                    )

                const data =
                    await response.json()

                console.log(data)

                statusDiv.innerText =
                    'Processando IA...'

            } catch (err) {

                console.error(err)

                statusDiv.innerText =
                    'Erro transcrevendo'
            }
        }

        // =================================
        // START
        // =================================

        recorder.start()

        startBtn.innerText =
            'Parar Gravação'

        statusDiv.innerText =
            'Gravando atendimento...'

    } catch (err) {

        console.error(err)

        statusDiv.innerText =
            'Erro: ' + err.message
    }
}