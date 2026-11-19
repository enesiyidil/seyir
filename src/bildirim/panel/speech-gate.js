// Keep a short lead-in so the first syllable survives voice detection.
class SpeechGate extends AudioWorkletProcessor {
  constructor() {
    super();
    this.listening = false;
    this.port.onmessage = ({data}) => {
      this.listening = data === "listen";
      this.lead = [];
      this.leadLength = 0;
      this.samples = [];
      this.length = this.quiet = this.voiced = 0;
      this.floor = 0.002;
    };
  }
  process(inputs) {
    const frame = inputs[0]?.[0];
    if (!this.listening || !frame?.length) return true;
    let power = 0;
    for (const sample of frame) power += sample * sample;
    const rms = Math.sqrt(power / frame.length);
    const voiced = rms > Math.max(0.008, this.floor * 3.2);
    const block = frame.slice();
    if (!this.length) {
      this.lead.push(block);
      this.leadLength += block.length;
      while (this.leadLength > sampleRate * 0.22) this.leadLength -= this.lead.shift().length;
      if (!voiced) {
        this.floor += 0.006 * (rms - this.floor);
        return true;
      }
      this.samples = this.lead;
      this.length = this.leadLength;
      this.lead = [];
      this.leadLength = 0;
    } else {
      this.samples.push(block);
      this.length += block.length;
    }
    if (voiced) {
      if (this.voiced < sampleRate * .1 && this.voiced + block.length >= sampleRate * .1)
        this.port.postMessage({state:"speech"});
      this.voiced += block.length;
      this.quiet = 0;
    } else this.quiet += block.length;
    if (this.quiet > sampleRate * .65 || this.length >= sampleRate * 24) {
      if (this.voiced > sampleRate * .12) {
        const pcm = new Float32Array(this.length);
        let offset = 0;
        for (const part of this.samples) { pcm.set(part, offset); offset += part.length; }
        this.listening = false;
        this.port.postMessage({pcm, rate:sampleRate}, [pcm.buffer]);
      } else this.port.postMessage({state:"quiet"});
      this.samples = [];
      this.length = this.voiced = this.quiet = 0;
    }
    return true;
  }
}
registerProcessor("speech-gate", SpeechGate);
