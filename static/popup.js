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
const finalizacoesPendentes = new Map()
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

    } else if (finalizacoesPendentes.size > 0) {

        rotulo =
            finalizacoesPendentes.size === 1
                ? 'Pronto — 1 atendimento finalizando em segundo plano'
                : `Pronto — ${finalizacoesPendentes.size} atendimentos finalizando em segundo plano`
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

function atendimentoEmAberto() {

    return Boolean(
        gravacaoAtiva ||
        finalizando ||
        atendimentoId ||
        finalizacoesPendentes.size > 0
    )
}

window.addEventListener('beforeunload', event => {

    if (!atendimentoEmAberto()) {

        return
    }

    event.preventDefault()
    event.returnValue = ''
})

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

async function enviarChunk(blob, ordem, duracaoMs, atendimentoIdDoUpload) {

    const formData =
        new FormData()

    formData.append(
        'atendimento_id',
        atendimentoIdDoUpload
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

async function finalizarAtendimento(contexto) {

    const response =
        await fetch('/atendimentos/finalizar', {
            method: 'POST',
            headers: csrfHeaders({
                'Content-Type': 'application/json',
            }),
            body: JSON.stringify({
                atendimento_id: contexto.atendimentoId,
                duracao_segundos: Math.floor(contexto.duracao / 1000),
                chunks_total: contexto.chunksTotal,
                chunks_falhos: contexto.chunksFalhos,
                chunks_ignorados: contexto.chunksIgnorados,
                segundos_transcritos: Math.floor(contexto.audioEnviadoMs / 1000)
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

    const atendimentoIdDoUpload =
        atendimentoId

    const ordemAtual =
        ordemChunk++

    audioEnviadoMs +=
        duracaoMs || TAMANHO_CHUNK_MS

    const upload =
        enviarChunk(
            blob,
            ordemAtual,
            duracaoMs,
            atendimentoIdDoUpload
        ).then(resultado => {

            if (
                resultado &&
                resultado.ignorado
            ) {

                return {ok: true, ordem: ordemAtual, ignorado: true}
            }

            if (
                atendimentoId === atendimentoIdDoUpload &&
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

            if (
                atendimentoId === atendimentoIdDoUpload
            ) {

                chunksFalhos++
            }

            if (
                err.devePararGravacao &&
                atendimentoId === atendimentoIdDoUpload
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

            if (
                atendimentoId === atendimentoIdDoUpload
            ) {

                statusDiv.innerText =
                    `Um trecho falhou, mas a gravacao continua (${chunksFalhos} falha(s))`
            }

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

function esperar(ms) {

    return new Promise(resolve => {
        setTimeout(resolve, ms)
    })
}

function resetarEstadoCaptura() {

    inicioLigacao = null
    duracaoFinalizacaoMs = null
    pausaIniciadaEm = null
    tempoPausadoMs = 0
    atendimentoId = null
    ordemChunk = 0
    chunksFalhos = 0
    chunksIgnorados = 0
    audioEnviadoMs = 0
    uploadsPendentes = []
    gravacaoAtiva = false
    pausado = false
    limiteAtingido = false
    recorder = null
    pararSegmentoAtual = null
}

async function concluirFinalizacaoEmSegundoPlano(contexto) {

    finalizacoesPendentes.set(
        contexto.atendimentoId,
        contexto
    )

    atualizarPainelGravacao()

    try {

        const resultadosUploads =
            await Promise.all(
                contexto.uploadsPendentes
            )

        contexto.chunksFalhos =
            resultadosUploads.filter(
                item => !item.ok
            ).length

        contexto.chunksIgnorados +=
            resultadosUploads.filter(
                item => item.ignorado
            ).length

        let resultadoFinal = null

        for (
            let tentativa = 0;
            tentativa < 20;
            tentativa++
        ) {

            resultadoFinal =
                await finalizarAtendimento(
                    contexto
                )

            if (
                resultadoFinal.status !== 'finalizando'
            ) {

                break
            }

            await esperar(2000)
        }

        if (
            !resultadoFinal ||
            resultadoFinal.status === 'finalizando'
        ) {

            throw new Error(
                'O resumo continua sendo gerado no servidor.'
            )
        }

        finalizacoesPendentes.delete(
            contexto.atendimentoId
        )

        window.dispatchEvent(
            new CustomEvent(
                'support-ai-atendimento-finalizado',
                {
                    detail: {
                        atendimentoId: contexto.atendimentoId,
                        chunksFalhos: contexto.chunksFalhos
                    }
                }
            )
        )

        if (
            !gravacaoAtiva &&
            !atendimentoId &&
            !finalizando
        ) {

            statusDiv.innerText =
                contexto.chunksFalhos > 0
                    ? 'Atendimento anterior finalizado com aviso - TMA: ' +
                        formatarTempo(contexto.duracao)
                    : 'Atendimento anterior finalizado - TMA: ' +
                        formatarTempo(contexto.duracao)
        }

    } catch (err) {

        console.error(err)

        finalizacoesPendentes.delete(
            contexto.atendimentoId
        )

        if (
            !gravacaoAtiva &&
            !atendimentoId &&
            !finalizando
        ) {

            statusDiv.innerText =
                `Atendimento ${contexto.atendimentoId} não finalizou: ${err.message}. Ele permanece no histórico para reprocessamento.`
        }

    } finally {

        atualizarPainelGravacao()
    }
}

async function finalizarGravacao() {

    if (finalizando || !atendimentoId) {
        return
    }

    const atendimentoEncerrado =
        atendimentoId

    startBtn.disabled =
        true

    atualizarBotaoPausa(false)

    statusDiv.innerText =
        'Encerrando captura e preparando finalização...'

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

        const contexto = {
            atendimentoId: atendimentoEncerrado,
            duracao: duracaoFinalizacaoMs,
            chunksTotal: ordemChunk,
            chunksFalhos: 0,
            chunksIgnorados: chunksIgnorados,
            audioEnviadoMs,
            uploadsPendentes: [
                ...uploadsPendentes
            ]
        }

        concluirFinalizacaoEmSegundoPlano(
            contexto
        )

        resetarEstadoCaptura()

        statusDiv.innerText =
            'Atendimento encerrado. Finalizando em segundo plano — você já pode iniciar outra gravação.'

    } catch (err) {

        console.error(err)

        statusDiv.innerText =
            'Erro encerrando atendimento: ' + err.message

    } finally {

        limparTimerChunk()

        startBtn.disabled =
            false

        startBtn.innerText =
            atendimentoId
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
