/**
 * Audio service handling microphone capture (16kHz PCM),
 * audio playback for Cartesia/Speechify TTS (24kHz PCM), and visualizer analysis.
 */

export class AudioManager {
  private inputAudioCtx: AudioContext | null = null
  private outputAudioCtx: AudioContext | null = null
  private micStream: MediaStream | null = null
  private processorNode: ScriptProcessorNode | null = null
  private muteGainNode: GainNode | null = null
  private inputAnalyser: AnalyserNode | null = null
  private outputAnalyser: AnalyserNode | null = null

  private nextPlayTime = 0
  private activeSources: AudioBufferSourceNode[] = []
  private isRecording = false
  private pcmRemainder: number | null = null

  /**
   * Start recording from the microphone and stream 16kHz mono PCM chunks.
   */
  async startRecording(onAudioChunk: (chunk: ArrayBuffer) => void): Promise<void> {
    if (this.isRecording) return

    // Get microphone stream
    this.micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })

    const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    this.inputAudioCtx = new AudioContextClass()

    const source = this.inputAudioCtx.createMediaStreamSource(this.micStream)

    // Analyser node for visualizer
    this.inputAnalyser = this.inputAudioCtx.createAnalyser()
    this.inputAnalyser.fftSize = 256
    source.connect(this.inputAnalyser)

    // 4096 buffer size at input sample rate gives smooth streaming
    this.processorNode = this.inputAudioCtx.createScriptProcessor(4096, 1, 1)
    const targetSampleRate = 16000
    const sourceSampleRate = this.inputAudioCtx.sampleRate

    this.processorNode.onaudioprocess = (e) => {
      if (!this.isRecording) return
      const inputData = e.inputBuffer.getChannelData(0)

      // Downsample to 16kHz if needed
      const downsampledData = this.resampleAudio(inputData, sourceSampleRate, targetSampleRate)
      const pcm16 = this.floatTo16BitPCM(downsampledData)
      onAudioChunk(pcm16.buffer as ArrayBuffer)
    }

    // Connect processor through a muted gain node so audio processing continues
    // without echoing the microphone input into the user's speakers
    this.muteGainNode = this.inputAudioCtx.createGain()
    this.muteGainNode.gain.value = 0

    source.connect(this.processorNode)
    this.processorNode.connect(this.muteGainNode)
    this.muteGainNode.connect(this.inputAudioCtx.destination)
    this.isRecording = true
  }

  /**
   * Stop recording and release microphone resources.
   */
  stopRecording(): void {
    this.isRecording = false
    if (this.processorNode) {
      this.processorNode.disconnect()
      this.processorNode = null
    }
    if (this.muteGainNode) {
      this.muteGainNode.disconnect()
      this.muteGainNode = null
    }
    if (this.micStream) {
      this.micStream.getTracks().forEach((track) => track.stop())
      this.micStream = null
    }
    if (this.inputAudioCtx && this.inputAudioCtx.state !== 'closed') {
      this.inputAudioCtx.close()
      this.inputAudioCtx = null
    }
    this.inputAnalyser = null
  }

  /**
   * Play a chunk of base64-encoded 24kHz PCM audio from Cartesia or Speechify TTS.
   */
  async playTTSChunk(base64Audio: string): Promise<void> {
    try {
      const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      if (!this.outputAudioCtx || this.outputAudioCtx.state === 'closed') {
        this.outputAudioCtx = new AudioContextClass({ sampleRate: 24000 })
        this.nextPlayTime = this.outputAudioCtx.currentTime
      }

      if (this.outputAudioCtx.state === 'suspended') {
        await this.outputAudioCtx.resume()
      }

      if (!this.outputAnalyser) {
        this.outputAnalyser = this.outputAudioCtx.createAnalyser()
        this.outputAnalyser.fftSize = 256
        this.outputAnalyser.connect(this.outputAudioCtx.destination)
      }

      // Decode base64 to binary
      const binaryString = atob(base64Audio)
      const rawLen = binaryString.length
      if (rawLen === 0) return

      // Prepend leftover byte from previous chunk if present to preserve 16-bit PCM sample alignment
      const hasRemainder = this.pcmRemainder !== null
      const totalLen = (hasRemainder ? 1 : 0) + rawLen
      const bytes = new Uint8Array(totalLen)
      let offset = 0
      if (hasRemainder) {
        bytes[0] = this.pcmRemainder!
        offset = 1
        this.pcmRemainder = null
      }
      for (let i = 0; i < rawLen; i++) {
        bytes[offset + i] = binaryString.charCodeAt(i)
      }

      // Retain trailing odd byte for next chunk if length is odd
      if (bytes.length % 2 !== 0) {
        this.pcmRemainder = bytes[bytes.length - 1]
      }

      const numSamples = Math.floor(bytes.length / 2)
      if (numSamples === 0) return

      const float32 = new Float32Array(numSamples)
      const dataView = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)

      for (let i = 0; i < numSamples; i++) {
        const int16 = dataView.getInt16(i * 2, true)
        float32[i] = int16 / 32768.0
      }

      // Create audio buffer at 24000Hz
      const audioBuffer = this.outputAudioCtx.createBuffer(1, numSamples, 24000)
      audioBuffer.getChannelData(0).set(float32)

      const source = this.outputAudioCtx.createBufferSource()
      source.buffer = audioBuffer
      source.connect(this.outputAnalyser)

      const currentTime = this.outputAudioCtx.currentTime
      const startTime = Math.max(currentTime, this.nextPlayTime)
      source.start(startTime)
      this.nextPlayTime = startTime + audioBuffer.duration

      this.activeSources.push(source)
      source.onended = () => {
        const idx = this.activeSources.indexOf(source)
        if (idx !== -1) {
          this.activeSources.splice(idx, 1)
        }
      }
    } catch (e) {
      console.error('[Audio] Error playing TTS chunk:', e)
    }
  }

  /**
   * Stop all active and scheduled audio playback immediately.
   */
  stopPlayback(): void {
    this.pcmRemainder = null
    for (const source of this.activeSources) {
      try {
        source.stop()
        source.disconnect()
      } catch {
        // Source might already have stopped
      }
    }
    this.activeSources = []
    if (this.outputAudioCtx) {
      this.nextPlayTime = this.outputAudioCtx.currentTime
    }
  }

  /**
   * Get current volume level (0 to 1) for microphone or output visualizer.
   */
  getVolumeLevel(): number {
    const analyser = this.isRecording ? this.inputAnalyser : this.outputAnalyser
    if (!analyser) return 0

    const dataArray = new Uint8Array(analyser.frequencyBinCount)
    analyser.getByteFrequencyData(dataArray)

    let sum = 0
    for (let i = 0; i < dataArray.length; i++) {
      sum += dataArray[i]
    }
    const average = sum / dataArray.length
    return Math.min(1, average / 128)
  }

  getIsRecording(): boolean {
    return this.isRecording
  }

  getIsPlaying(): boolean {
    return this.activeSources.length > 0
  }

  private resampleAudio(input: Float32Array, inSampleRate: number, outSampleRate: number): Float32Array {
    if (inSampleRate === outSampleRate) return input
    const ratio = inSampleRate / outSampleRate
    const outputLength = Math.round(input.length / ratio)
    const result = new Float32Array(outputLength)

    for (let i = 0; i < outputLength; i++) {
      const originalIndex = i * ratio
      const indexFloor = Math.floor(originalIndex)
      const indexCeil = Math.min(input.length - 1, Math.ceil(originalIndex))
      const weight = originalIndex - indexFloor
      result[i] = (1 - weight) * input[indexFloor] + weight * input[indexCeil]
    }
    return result
  }

  private floatTo16BitPCM(input: Float32Array): Int16Array {
    const output = new Int16Array(input.length)
    for (let i = 0; i < input.length; i++) {
      const s = Math.max(-1, Math.min(1, input[i]))
      output[i] = s < 0 ? s * 0x8000 : s * 0x7fff
    }
    return output
  }
}

export const audioManager = new AudioManager()
