import { describe, it, expect, vi, beforeEach } from 'vitest'
import { AudioManager, audioManager } from './audio'

describe('AudioManager', () => {
  let manager: AudioManager

  beforeEach(() => {
    manager = new AudioManager()
  })

  it('has initial state not recording and not playing', () => {
    expect(manager.getIsRecording()).toBe(false)
    expect(manager.getIsPlaying()).toBe(false)
    expect(manager.getVolumeLevel()).toBe(0)
  })

  it('safely handles stopPlayback and stopRecording when idle', () => {
    expect(() => manager.stopPlayback()).not.toThrow()
    expect(() => manager.stopRecording()).not.toThrow()
    expect(manager.getIsPlaying()).toBe(false)
  })

  it('converts float audio buffer to 16-bit PCM correctly', () => {
    const floatTo16BitPCM = (manager as any).floatTo16BitPCM.bind(manager)
    const input = new Float32Array([0.0, 1.0, -1.0, 0.5, -0.5])
    const pcm: Int16Array = floatTo16BitPCM(input)

    expect(pcm.length).toBe(5)
    expect(pcm[0]).toBe(0)
    expect(pcm[1]).toBe(32767)
    expect(pcm[2]).toBe(-32768)
    expect(pcm[3]).toBe(Math.floor(0.5 * 32767))
  })

  it('resamples audio buffer accurately', () => {
    const resampleAudio = (manager as any).resampleAudio.bind(manager)

    // Identity resample
    const input = new Float32Array([0.1, 0.2, 0.3, 0.4])
    const identity = resampleAudio(input, 16000, 16000)
    expect(identity).toBe(input)

    // Downsample 48kHz to 16kHz (ratio 3)
    const input48k = new Float32Array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5])
    const output16k: Float32Array = resampleAudio(input48k, 48000, 16000)
    expect(output16k.length).toBe(2)
  })

  it('plays TTS chunk and calculates volume level with mock AudioContext', async () => {
    class MockAudioContext {
      state = 'suspended'
      currentTime = 0
      destination = {}
      createBuffer(_channels: number, length: number, sampleRate: number) {
        return {
          duration: length / sampleRate,
          getChannelData: () => new Float32Array(length),
        }
      }
      createBufferSource() {
        return {
          buffer: null,
          connect: vi.fn(),
          start: vi.fn(),
          stop: vi.fn(),
          disconnect: vi.fn(),
          onended: null,
        }
      }
      createAnalyser() {
        return {
          fftSize: 256,
          frequencyBinCount: 128,
          connect: vi.fn(),
          getByteFrequencyData: vi.fn((arr: Uint8Array) => arr.fill(64)),
        }
      }
      resume = vi.fn().mockResolvedValue(undefined)
      close = vi.fn().mockResolvedValue(undefined)
    }

    const origAudioContext = (window as any).AudioContext
    ;(window as any).AudioContext = MockAudioContext

    // Create 4 bytes representing two 16-bit PCM samples
    const sampleBytes = new Uint8Array([0, 0, 100, 0])
    const base64Audio = btoa(String.fromCharCode(...sampleBytes))

    await manager.playTTSChunk(base64Audio)
    expect(manager.getIsPlaying()).toBe(true)

    const volume = manager.getVolumeLevel()
    expect(volume).toBeGreaterThan(0)

    manager.stopPlayback()
    expect(manager.getIsPlaying()).toBe(false)

    ;(window as any).AudioContext = origAudioContext
  })

  it('starts and stops recording with mock mediaDevices', async () => {
    let capturedCallback: any = null

    class MockRecordContext {
      sampleRate = 48000
      state = 'running'
      destination = {}
      createMediaStreamSource() {
        return { connect: vi.fn() }
      }
      createAnalyser() {
        return {
          fftSize: 256,
          frequencyBinCount: 128,
          connect: vi.fn(),
          getByteFrequencyData: vi.fn((arr: Uint8Array) => arr.fill(32)),
        }
      }
      createScriptProcessor() {
        const node = {
          connect: vi.fn(),
          disconnect: vi.fn(),
          onaudioprocess: null as any,
        }
        capturedCallback = node
        return node
      }
      createGain() {
        return {
          connect: vi.fn(),
          disconnect: vi.fn(),
          gain: { value: 0 },
        }
      }
      close = vi.fn().mockResolvedValue(undefined)
    }

    const origAudioContext = (window as any).AudioContext
    ;(window as any).AudioContext = MockRecordContext

    const stopTrack = vi.fn()
    ;(navigator as any).mediaDevices = {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: stopTrack }],
      }),
    }

    const onChunk = vi.fn()
    await manager.startRecording(onChunk)
    expect(manager.getIsRecording()).toBe(true)

    // Simulate audio process event
    if (capturedCallback && capturedCallback.onaudioprocess) {
      capturedCallback.onaudioprocess({
        inputBuffer: {
          getChannelData: () => new Float32Array([0.1, 0.2, 0.3]),
        },
      })
      expect(onChunk).toHaveBeenCalled()
    }

    manager.stopRecording()
    expect(manager.getIsRecording()).toBe(false)
    expect(stopTrack).toHaveBeenCalled()

    ;(window as any).AudioContext = origAudioContext
  })

  it('exports singleton audioManager instance', () => {
    expect(audioManager).toBeInstanceOf(AudioManager)
  })
})
