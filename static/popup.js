const startBtn =
    document.getElementById('start')

const statusDiv =
    document.getElementById('status')

let recorder = null
let screenStream = null
let micStream = null
let inicioLigacao = null
let atendimentoId = null
let ordemChunk = 0
let uploadsPendentes = []

const TAMANHO_CHUNK_MS = 30000

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
// ATENDIMENTO
// =====================================

async function iniciarAtendimento() {

    const response =
        await fetch('/atendimentos/iniciar', {
            method: 'POST'
        })

    const data =
        await response.json()

    if (!response.ok) {

        throw new Error(
            data.erro || 'Erro iniciando atendimento'
        )
    }

    return data.atendimento_id
}

async function enviarChunk(blob, ordem) {

    const formData =
        new FormData()

    formData.append(
        'atendimento_id',
        atendimentoId
    )

    formData.append(
        'ordem',
        ordem
    )

    formData.append(
        'audio',
        blob,
        `chunk-${ordem}.webm`
    )

    const response =
        await fetch('/atendimentos/chunk', {
            method: 'POST',
            body: formData
        })

    const data =
        await response.json()

    if (!response.ok) {

        throw new Error(
            data.erro || 'Erro transcrevendo trecho'
        )
    }

    return data
}

async function finalizarAtendimento(duracao) {

    const response =
        await fetch('/atendimentos/finalizar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                atendimento_id: atendimentoId,
                duracao_segundos: Math.floor(duracao / 1000)
            })
        })

    const data =
        await response.json()

    if (!response.ok) {

        throw new Error(
            data.erro || 'Erro finalizando atendimento'
        )
    }

    return data
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

        startBtn.disabled = true

        statusDiv.innerText =
            'Finalizando e aguardando ultimos trechos...'

        return
    }

    try {

        statusDiv.innerText =
            'Escolha a aba do 55PBX'

        inicioLigacao =
            Date.now()

        atendimentoId =
            await iniciarAtendimento()

        ordemChunk = 0
        uploadsPendentes = []

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

        const finalStream =
            destination.stream

        recorder =
            new MediaRecorder(
                finalStream,
                {
                    mimeType: 'audio/webm'
                }
            )

        recorder.ondataavailable = event => {

            if (
                event.data &&
                event.data.size > 0
            ) {

                const ordemAtual =
                    ordemChunk++

                const upload =
                    enviarChunk(
                        event.data,
                        ordemAtual
                    ).then(() => {

                        statusDiv.innerText =
                            `Gravando e transcrevendo... trecho ${ordemAtual + 1}`

                    }).catch(err => {

                        console.error(err)

                        statusDiv.innerText =
                            'Erro em um trecho da transcricao'
                    })

                uploadsPendentes.push(upload)
            }
        }

        recorder.onstop = async () => {

            try {

                screenStream
                    .getTracks()
                    .forEach(t => t.stop())

                micStream
                    .getTracks()
                    .forEach(t => t.stop())

                const fimLigacao =
                    Date.now()

                const duracao =
                    fimLigacao - inicioLigacao

                await Promise.all(
                    uploadsPendentes
                )

                statusDiv.innerText =
                    'Gerando resumo final...'

                await finalizarAtendimento(
                    duracao
                )

                statusDiv.innerText =
                    'Ligacao finalizada - TMA: ' +
                    formatarTempo(duracao)

            } catch (err) {

                console.error(err)

                statusDiv.innerText =
                    'Erro finalizando atendimento'

            } finally {

                startBtn.disabled = false

                startBtn.innerText =
                    'Iniciar Gravacao'

                atendimentoId = null
            }
        }

        recorder.start(
            TAMANHO_CHUNK_MS
        )

        startBtn.innerText =
            'Parar Gravacao'

        statusDiv.innerText =
            'Gravando e transcrevendo em trechos...'

    } catch (err) {

        console.error(err)

        statusDiv.innerText =
            'Erro: ' + err.message

        startBtn.disabled = false

        if (screenStream) {
            screenStream
                .getTracks()
                .forEach(t => t.stop())
        }

        if (micStream) {
            micStream
                .getTracks()
                .forEach(t => t.stop())
        }
    }
}
