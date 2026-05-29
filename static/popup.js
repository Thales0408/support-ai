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
let chunksFalhos = 0
let uploadsPendentes = []

const TAMANHO_CHUNK_MS = 30000

async function lerRespostaJson(response, mensagemPadrao) {

    const contentType =
        response.headers.get('content-type') || ''

    if (
        contentType.includes('application/json')
    ) {

        return await response.json()
    }

    await response.text()

    throw new Error(
        mensagemPadrao + ': servidor retornou uma pagina de erro'
    )
}

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
        await lerRespostaJson(
            response,
            'Erro iniciando atendimento'
        )

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
        await lerRespostaJson(
            response,
            'Erro transcrevendo trecho'
        )

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
                duracao_segundos: Math.floor(duracao / 1000),
                chunks_total: ordemChunk,
                chunks_falhos: chunksFalhos
            })
        })

    const data =
        await lerRespostaJson(
            response,
            'Erro finalizando atendimento'
        )

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

        ordemChunk = 0
        chunksFalhos = 0
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

        statusDiv.innerText =
            'Criando atendimento...'

        atendimentoId =
            await iniciarAtendimento()

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

        const opcoesRecorder =
            MediaRecorder.isTypeSupported('audio/webm')
                ? {
                    mimeType: 'audio/webm'
                }
                : undefined

        recorder =
            new MediaRecorder(
                finalStream,
                opcoesRecorder
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

                        return {
                            ok: true,
                            ordem: ordemAtual
                        }

                    }).catch(err => {

                        console.error(err)

                        chunksFalhos++

                        statusDiv.innerText =
                            `Um trecho falhou, mas a gravacao continua (${chunksFalhos} falha(s))`

                        return {
                            ok: false,
                            ordem: ordemAtual,
                            erro: err.message
                        }
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

                const resultadosUploads =
                    await Promise.all(
                    uploadsPendentes
                    )

                chunksFalhos =
                    resultadosUploads.filter(
                        item => !item.ok
                    ).length

                statusDiv.innerText =
                    chunksFalhos > 0
                        ? `Gerando resumo final com ${chunksFalhos} trecho(s) com falha...`
                        : 'Gerando resumo final...'

                await finalizarAtendimento(
                    duracao
                )

                statusDiv.innerText =
                    chunksFalhos > 0
                        ? 'Ligacao finalizada com aviso - TMA: ' +
                            formatarTempo(duracao)
                        : 'Ligacao finalizada - TMA: ' +
                            formatarTempo(duracao)

            } catch (err) {

                console.error(err)

                statusDiv.innerText =
                    'Erro finalizando atendimento: ' + err.message

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
