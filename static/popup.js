const startBtn =
    document.getElementById('start')

const pauseBtn =
    document.getElementById('pause')

const statusDiv =
    document.getElementById('status')

let recorder = null
let screenStream = null
let micStream = null
let finalStream = null
let audioContext = null
let chunkTimer = null
let inicioLigacao = null
let pausaIniciadaEm = null
let tempoPausadoMs = 0
let atendimentoId = null
let ordemChunk = 0
let chunksFalhos = 0
let chunksIgnorados = 0
let audioEnviadoMs = 0
let uploadsPendentes = []
let gravacaoAtiva = false
let pausado = false
let finalizando = false
let pararSegmentoAtual = null

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

function atualizarBotaoPausa(visivel, estaPausado = false) {

    pauseBtn.style.display =
        visivel ? 'inline-block' : 'none'

    pauseBtn.disabled =
        !visivel

    pauseBtn.innerText =
        estaPausado ? 'Continuar' : 'Pausar'
}

function limparTimerChunk() {

    if (
        chunkTimer
    ) {

        clearTimeout(chunkTimer)
        chunkTimer = null
    }
}

function pararStreams() {

    if (
        screenStream
    ) {

        screenStream
            .getTracks()
            .forEach(t => t.stop())
    }

    if (
        micStream
    ) {

        micStream
            .getTracks()
            .forEach(t => t.stop())
    }

    if (
        audioContext
    ) {

        audioContext.close()
    }

    screenStream = null
    micStream = null
    finalStream = null
    audioContext = null
}

// =====================================
// ATENDIMENTO
// =====================================

async function iniciarAtendimento() {

    const ticketInput =
        document.getElementById('ticket-zendesk')

    const response =
        await fetch('/atendimentos/iniciar', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                ticket_zendesk: ticketInput ? ticketInput.value : ''
            })
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
                chunks_falhos: chunksFalhos,
                chunks_ignorados: chunksIgnorados,
                segundos_transcritos: Math.floor(audioEnviadoMs / 1000)
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

function registrarUpload(blob, duracaoMs) {

    if (
        !blob ||
        blob.size < 512 ||
        !atendimentoId
    ) {

        return
    }

    const ordemAtual =
        ordemChunk++

    audioEnviadoMs +=
        duracaoMs || TAMANHO_CHUNK_MS

    const upload =
        enviarChunk(
            blob,
            ordemAtual
        ).then(resultado => {

            if (
                resultado &&
                resultado.ignorado
            ) {

                return resultado
            }

            if (
                gravacaoAtiva &&
                !pausado
            ) {

                statusDiv.innerText =
                        `Gravando e transcrevendo... trecho ${ordemAtual + 1}`
            }

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

function iniciarNovoSegmento() {

    if (
        !gravacaoAtiva ||
        pausado ||
        finalizando ||
        !finalStream
    ) {

        return Promise.resolve()
    }

    limparTimerChunk()

    const opcoesRecorder =
        MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
            ? {
                mimeType: 'audio/webm;codecs=opus'
            }
            : (
                MediaRecorder.isTypeSupported('audio/webm')
                    ? {
                        mimeType: 'audio/webm'
                    }
                    : undefined
            )

    const partes =
        []

    const inicioSegmento =
        Date.now()

    recorder =
        new MediaRecorder(
            finalStream,
            opcoesRecorder
        )

    const encerramento =
        new Promise(resolve => {

            recorder.ondataavailable = event => {

                if (
                    event.data &&
                    event.data.size > 0
                ) {

                    partes.push(event.data)
                }
            }

            recorder.onstop = () => {

                limparTimerChunk()

                if (
                    partes.length
                ) {

                    const blob =
                        new Blob(
                            partes,
                            {
                                type: recorder.mimeType || 'audio/webm'
                            }
                        )

                    registrarUpload(
                        blob,
                        Date.now() - inicioSegmento
                    )
                }

                const deveContinuar =
                    gravacaoAtiva &&
                    !pausado &&
                    !finalizando

                recorder = null
                pararSegmentoAtual = null

                if (
                    deveContinuar
                ) {

                    iniciarNovoSegmento()
                }

                resolve()
            }
        })

    pararSegmentoAtual =
        encerramento

    recorder.start()

    chunkTimer =
        setTimeout(() => {

            if (
                recorder &&
                recorder.state === 'recording'
            ) {

                recorder.stop()
            }
        }, TAMANHO_CHUNK_MS)

    return encerramento
}

async function pararSegmentoSeNecessario() {

    if (
        recorder &&
        recorder.state === 'recording'
    ) {

        recorder.stop()
    }

    if (
        pararSegmentoAtual
    ) {

        await pararSegmentoAtual
    }
}

async function finalizarGravacao() {

    startBtn.disabled =
        true

    atualizarBotaoPausa(false)

    statusDiv.innerText =
        'Finalizando e aguardando ultimos trechos...'

    finalizando =
        true

    if (
        pausaIniciadaEm
    ) {

        tempoPausadoMs +=
            Date.now() - pausaIniciadaEm
    }

    pausaIniciadaEm =
        null

    gravacaoAtiva =
        false

    pausado =
        false

    try {

        await pararSegmentoSeNecessario()

        pararStreams()

        const fimLigacao =
            Date.now()

        const duracao =
            Math.max(
                0,
                fimLigacao - inicioLigacao - tempoPausadoMs
            )

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

        limparTimerChunk()

        startBtn.disabled =
            false

        startBtn.innerText =
            'Iniciar Gravacao'

        atualizarBotaoPausa(false)

        recorder = null
        atendimentoId = null
        finalizando = false
    }
}

// =====================================
// CLICK
// =====================================

pauseBtn.onclick = async () => {

    if (
        !gravacaoAtiva ||
        finalizando
    ) {

        return
    }

    if (
        !pausado
    ) {

        pausado =
            true

        pausaIniciadaEm =
            Date.now()

        atualizarBotaoPausa(
            true,
            true
        )

        statusDiv.innerText =
            'Pausando transcricao e fechando o trecho atual...'

        await pararSegmentoSeNecessario()

        statusDiv.innerText =
            'Transcricao pausada. Nenhum audio sera enviado ate continuar.'

        return
    }

    if (
        pausaIniciadaEm
    ) {

        tempoPausadoMs +=
            Date.now() - pausaIniciadaEm
    }

    pausaIniciadaEm =
        null

    pausado =
        false

    atualizarBotaoPausa(
        true,
        false
    )

    statusDiv.innerText =
        'Gravacao retomada. Transcrevendo novos trechos...'

    iniciarNovoSegmento()
}

startBtn.onclick = async () => {

    // =================================
    // PARAR
    // =================================

    if (
        gravacaoAtiva ||
        finalizando
    ) {

        await finalizarGravacao()
        return
    }

    try {

        statusDiv.innerText =
            'Escolha a aba do 55PBX'

        inicioLigacao =
            Date.now()

        pausaIniciadaEm = null
        tempoPausadoMs = 0
        ordemChunk = 0
        chunksFalhos = 0
        chunksIgnorados = 0
        audioEnviadoMs = 0
        uploadsPendentes = []
        gravacaoAtiva = false
        pausado = false
        finalizando = false
        pararSegmentoAtual = null
        atualizarBotaoPausa(false)

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

        audioContext =
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

        finalStream =
            destination.stream

        gravacaoAtiva =
            true

        iniciarNovoSegmento()

        startBtn.innerText =
            'Parar Gravacao'

        atualizarBotaoPausa(true)

        statusDiv.innerText =
            'Gravando e transcrevendo em trechos...'

    } catch (err) {

        console.error(err)

        statusDiv.innerText =
            'Erro: ' + err.message

        startBtn.disabled = false
        startBtn.innerText =
            'Iniciar Gravacao'

        atualizarBotaoPausa(false)
        limparTimerChunk()
        pararStreams()

        recorder = null
        atendimentoId = null
        gravacaoAtiva = false
        pausado = false
        finalizando = false
    }
}
