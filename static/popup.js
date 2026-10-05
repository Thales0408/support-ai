const startBtn =
    document.getElementById('start')

const pauseBtn =
    document.getElementById('pause')

const statusDiv =
    document.getElementById('status')

const captureShell =
    document.getElementById('capture-shell')

const captureStateLabel =
    document.getElementById('capture-state-label')

const recordingTimer =
    document.getElementById('recording-timer')

let recorder = null
let screenStream = null
let micStream = null
let finalStream = null
let audioContext = null
let chunkTimer = null
let inicioLigacao = null
let duracaoFinalizacaoMs = null
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
let limiteAtingido = false
let pararSegmentoAtual = null
let analisadoresAudio = []
let monitorAtividade = null

const TAMANHO_CHUNK_MS =
    Math.max(
        10,
        Number(window.SUPPORT_AI_CHUNK_SECONDS || 45)
    ) * 1000

const GANHO_ABA =
    Number(window.SUPPORT_AI_SYSTEM_GAIN || 1)

const GANHO_MICROFONE =
    Number(window.SUPPORT_AI_MIC_GAIN || 0.85)

const LIMIAR_ATIVIDADE_AUDIO = 0.006

function adicionarAnalisador(noAudio) {
    const node = audioContext.createAnalyser()
    node.fftSize = 2048
    noAudio.connect(node)
    analisadoresAudio.push({
        node,
        amostras: new Float32Array(node.fftSize)
    })
    return node
}

function nivelAudio(analisador) {
    analisador.node.getFloatTimeDomainData(analisador.amostras)

    let soma = 0
    for (const amostra of analisador.amostras) {
        soma += amostra * amostra
    }

    return Math.sqrt(soma / analisador.amostras.length)
}

function csrfToken() {

    const meta =
        document.querySelector('meta[name="csrf-token"]')

    return meta
        ? meta.getAttribute('content')
        : ''
}

function csrfHeaders(headers = {}) {

    const token =
        csrfToken()

    return {
        ...headers,
        'X-CSRF-Token': token,
        'X-CSRFToken': token
    }
}

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

function formatarCronometro(ms) {

    const totalSegundos =
        Math.max(0, Math.floor((ms || 0) / 1000))

    const horas =
        Math.floor(totalSegundos / 3600)

    const minutos =
        Math.floor((totalSegundos % 3600) / 60)

    const segundos =
        totalSegundos % 60

    return horas > 0
        ? `${String(horas).padStart(2, '0')}:${String(minutos).padStart(2, '0')}:${String(segundos).padStart(2, '0')}`
        : `${String(minutos).padStart(2, '0')}:${String(segundos).padStart(2, '0')}`
}

function duracaoVisualAtual() {

    if (!inicioLigacao) {

        return 0
    }

    if (duracaoFinalizacaoMs !== null) {

        return duracaoFinalizacaoMs
    }

    const agora =
        Date.now()

    const pausaAtual =
        pausaIniciadaEm
            ? agora - pausaIniciadaEm
            : 0

    return Math.max(
        0,
        agora - inicioLigacao - tempoPausadoMs - pausaAtual
    )
}

function atualizarPainelGravacao() {

    if (!captureShell) {

        return
    }

    let estado =
        'idle'

    let rotulo =
        'Pronto para iniciar'

    if (finalizando) {

        estado =
            'finalizing'

        rotulo =
            'Finalizando atendimento'

    } else if (limiteAtingido && atendimentoId) {

        estado =
            'paused'

        rotulo =
            'Limite atingido — finalize o atendimento'

    } else if (gravacaoAtiva && pausado) {

        estado =
            'paused'

        rotulo =
            'Gravação pausada'

    } else if (gravacaoAtiva) {

        estado =
            'recording'

        rotulo =
            'Gravando atendimento'

    } else if (atendimentoId) {

        estado =
            'paused'

        rotulo =
            'Aguardando finalização'
    }

    captureShell.dataset.state =
        estado

    if (captureStateLabel) {

        captureStateLabel.innerText =
            rotulo
    }

    if (recordingTimer) {

        recordingTimer.innerText =
            (
                gravacaoAtiva ||
                atendimentoId ||
                finalizando
            )
                ? formatarCronometro(duracaoVisualAtual())
                : '00:00'
    }
}

setInterval(
    atualizarPainelGravacao,
    1000
)

atualizarPainelGravacao()

function atualizarBotaoPausa(visivel, estaPausado = false) {

    pauseBtn.style.display =
        visivel ? 'inline-block' : 'none'

    pauseBtn.disabled =
        !visivel

    pauseBtn.innerText =
        estaPausado ? 'Continuar' : 'Pausar'

    atualizarPainelGravacao()
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

    if (monitorAtividade) {
        clearInterval(monitorAtividade)
        monitorAtividade = null
    }

    analisadoresAudio = []

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
        document.getElementById('ticket-clickdesk')

    const response =
        await fetch('/atendimentos/iniciar', {
            method: 'POST',
            headers: csrfHeaders({
                'Content-Type': 'application/json',
            }),
            body: JSON.stringify({
                ticket_clickdesk: ticketInput ? ticketInput.value : ''
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

async function enviarChunk(blob, ordem, duracaoMs) {

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
        'duracao_segundos',
        Math.floor((duracaoMs || TAMANHO_CHUNK_MS) / 1000)
    )

    formData.append(
        'audio',
        blob,
        `chunk-${ordem}.webm`
    )

    const response =
        await fetch('/atendimentos/chunk', {
            method: 'POST',
            headers: csrfHeaders(),
            body: formData
        })

    const data =
        await lerRespostaJson(
            response,
            'Erro transcrevendo trecho'
        )

    if (!response.ok) {

        const erro =
            new Error(
                data.mensagem ||
                data.erro ||
                'Erro transcrevendo trecho'
            )

        erro.limite =
            Boolean(data.limite)

        erro.tipo =
            data.tipo

        erro.devePararGravacao =
            Boolean(data.deve_parar_gravacao)

        throw erro
    }

    return data
}

async function pararGravacaoPorLimite(mensagem) {

    if (
        limiteAtingido ||
        finalizando
    ) {

        return
    }

    limiteAtingido =
        true

    pausado =
        true

    atualizarPainelGravacao()

    limparTimerChunk()

    atualizarBotaoPausa(false)

    statusDiv.innerText =
        mensagem ||
        'Limite diario de minutos atingido. A gravacao foi pausada automaticamente. Finalize o atendimento para gerar o resumo com o conteudo ja capturado.'

    startBtn.innerText =
        'Finalizar atendimento'

    startBtn.disabled =
        false

    if (
        recorder &&
        recorder.state === 'recording'
    ) {

        recorder.stop()
    }

    pararStreams()
}

async function finalizarAtendimento(duracao) {

    const response =
        await fetch('/atendimentos/finalizar', {
            method: 'POST',
            headers: csrfHeaders({
                'Content-Type': 'application/json',
            }),
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
            data.mensagem || data.erro || 'Erro finalizando atendimento'
        )
    }

    if (data.status === 'finalizando') {
        throw new Error(data.mensagem || 'Resumo ainda esta sendo gerado. Tente novamente.')
    }

    return data
}

function registrarUpload(blob, duracaoMs, temAtividade = true) {

    if (
        !blob ||
        blob.size < 512 ||
        !atendimentoId ||
        limiteAtingido
    ) {

        return
    }

    if (analisadoresAudio.length && !temAtividade) {
        chunksIgnorados++
        return
    }

    const ordemAtual =
        ordemChunk++

    audioEnviadoMs +=
        duracaoMs || TAMANHO_CHUNK_MS

    const upload =
        enviarChunk(
            blob,
            ordemAtual,
            duracaoMs
        ).then(resultado => {

            if (
                resultado &&
                resultado.ignorado
            ) {

                chunksIgnorados++
                return {ok: true, ordem: ordemAtual, ignorado: true}
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

            if (
                err.devePararGravacao
            ) {

                pararGravacaoPorLimite(
                    err.message ||
                    'Limite diario de minutos atingido. A gravacao foi pausada automaticamente. Finalize o atendimento para gerar o resumo com o conteudo ja capturado.'
                )

                return {
                    ok: false,
                    ordem: ordemAtual,
                    limite: true,
                    erro: err.message
                }
            }

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
                mimeType: 'audio/webm;codecs=opus',
                audioBitsPerSecond: 128000
            }
            : (
                MediaRecorder.isTypeSupported('audio/webm')
                    ? {
                        mimeType: 'audio/webm',
                        audioBitsPerSecond: 128000
                    }
                    : undefined
            )

    const partes =
        []

    const inicioSegmento =
        Date.now()

    let amostrasAtivas = 0
    let maiorNivel = 0
    let amostrasLidas = 0

    if (analisadoresAudio.length) {
        monitorAtividade = setInterval(() => {
            if (audioContext.state !== 'running') {
                return
            }
            const nivel = Math.max(
                ...analisadoresAudio.map(nivelAudio)
            )
            amostrasLidas++
            maiorNivel = Math.max(maiorNivel, nivel)
            if (nivel >= LIMIAR_ATIVIDADE_AUDIO) {
                amostrasAtivas++
            }
        }, 100)
    }

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

                if (monitorAtividade) {
                    clearInterval(monitorAtividade)
                    monitorAtividade = null
                }

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
                        Date.now() - inicioSegmento,
                        amostrasLidas < 2 ||
                        audioContext.state !== 'running' ||
                        amostrasAtivas >= 2 ||
                        maiorNivel >= 0.03
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

    if (finalizando || !atendimentoId) {
        return
    }

    startBtn.disabled =
        true

    atualizarBotaoPausa(false)

    statusDiv.innerText =
        'Finalizando e aguardando ultimos trechos...'

    finalizando =
        true

    atualizarPainelGravacao()

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

        if (duracaoFinalizacaoMs === null) {
            duracaoFinalizacaoMs = Math.max(
                0,
                Date.now() - inicioLigacao - tempoPausadoMs
            )
        }

        const duracao = duracaoFinalizacaoMs

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

        atendimentoId = null
        duracaoFinalizacaoMs = null

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

        startBtn.innerText = atendimentoId
            ? 'Tentar finalizar'
            : 'Iniciar gravação'

        atualizarBotaoPausa(false)

        recorder = null
        finalizando = false

        atualizarPainelGravacao()
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
            'Pausando transcrição e fechando o trecho atual...'

        await pararSegmentoSeNecessario()

        statusDiv.innerText =
            'Transcrição pausada. Nenhum áudio será enviado até continuar.'

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
        'Gravação retomada. Transcrevendo novos trechos...'

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

    if (atendimentoId) {
        await finalizarGravacao()
        return
    }

    try {

        statusDiv.innerText =
            'Selecione a aba do 55PBX para capturar o áudio'

        inicioLigacao =
            null

        duracaoFinalizacaoMs = null

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
        limiteAtingido = false
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
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        autoGainControl: true,
                        channelCount: 1
                    }
                })

        statusDiv.innerText =
            'Preparando atendimento...'

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

        const channelMerger =
            audioContext.createChannelMerger(2)

        let conectouCanal =
            false

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

            const systemGain =
                audioContext.createGain()

            systemGain.gain.value =
                Number.isFinite(GANHO_ABA) ? GANHO_ABA : 1

            systemSource.connect(systemGain)
            adicionarAnalisador(systemGain).connect(channelMerger, 0, 0)
            conectouCanal = true
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

            const micGain =
                audioContext.createGain()

            micGain.gain.value =
                Number.isFinite(GANHO_MICROFONE) ? GANHO_MICROFONE : 0.85

            micSource.connect(micGain)
            adicionarAnalisador(micGain).connect(channelMerger, 0, 1)
            conectouCanal = true
        }

        if (
            conectouCanal
        ) {

            channelMerger.connect(destination)
        }

        finalStream =
            destination.stream

        inicioLigacao =
            Date.now()

        gravacaoAtiva =
            true

        atualizarPainelGravacao()

        iniciarNovoSegmento()

        startBtn.innerText =
            'Finalizar atendimento'

        atualizarBotaoPausa(true)

        statusDiv.innerText =
            'Gravando e transcrevendo em tempo real...'

    } catch (err) {

        console.error(err)

        statusDiv.innerText =
            'Erro: ' + err.message

        startBtn.disabled = false
        startBtn.innerText =
            'Iniciar gravação'

        atualizarBotaoPausa(false)
        limparTimerChunk()
        pararStreams()

        recorder = null
        atendimentoId = null
        gravacaoAtiva = false
        pausado = false
        finalizando = false

        atualizarPainelGravacao()
    }
}
