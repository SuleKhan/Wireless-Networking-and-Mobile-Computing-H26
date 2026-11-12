# Assignment 8 AI Chat Log

This log summarizes the assignment-related exchanges with GitHub Copilot in this chat. User-provided measurements and results are identified as such; they were not independently measured by Copilot.

## Step 1: Theory

**User**

Does acoustic communication rely on electromagnetic waves? How fast does sound travel through air? What are typical smartphone recording bandwidth and human hearing range? Calculate wavelengths, the Nyquist limit, and explain why phase encoding is sensitive to movement. How can a receiver find the start of a message?

**Assistant**

Acoustic communication uses mechanical pressure waves in a medium, not electromagnetic waves. Sound travels through air at about 343 m/s at room temperature. Smartphone audio sampling rates commonly include 44.1 kHz or 48 kHz, corresponding to theoretical Nyquist limits of 22.05 kHz or 24 kHz; the actual microphone response may be narrower. A commonly cited human hearing range is about 20 Hz–20 kHz.

Using \(\lambda=c/f\), wavelengths are about 3.43 m at 100 Hz, 0.343 m at 1 kHz, and 2.29 cm at 15 kHz. A signal sampled at 16 kHz has an 8 kHz Nyquist limit. At 1 kHz, moving 1 cm changes path-related phase by about 10.5 degrees, so movements of several centimetres can disturb phase-coded data. A known preamble or synchronization sequence can be detected, often by correlation, to locate the message.

The assistant also reformatted this response in Markdown with math delimiters to render properly in the notebook.

## Step 2: Audio Analysis

### Time and frequency domain

**User**

Interpret the 5-second time-domain plots of `CrabRave.wav` and `DarudeSandstorm.wav`.

**Assistant**

The provided plots show *CrabRave* maintaining a fairly high, fluctuating amplitude across the segment, with no obvious silent interval. *DarudeSandstorm* swells to a strong burst around 0.8–1 second and then decays; after about 2 seconds it is much quieter but not clearly silent.

**User**

Interpret the frequency-domain plots and identify where the magnitude is highest and lowest.

**Assistant**

A spectrum displays magnitude or energy by frequency. In the supplied plots, both tracks have components across most of the displayed 0–8 kHz range. The strongest magnitudes are generally at low frequencies, while the spectra drop sharply near 8 kHz, the Nyquist limit for a 16 kHz sample rate.

### Spectrogram and tempo

**User**

Explain the spectrogram patterns, their source, count the beats in five seconds, and compare with the notebook tempo estimate.

**Assistant**

A spectrogram shows how signal magnitude across frequencies changes over time. Repeated vertical changes can correspond to percussive events such as drum or kick hits. The assistant initially estimated about 125 BPM for *CrabRave* and 109 BPM for *DarudeSandstorm* by reproducing the notebook estimator. The user then reported that their notebook gave 136 BPM for *DarudeSandstorm*. The assistant corrected the response to use the user's notebook result: 136 BPM corresponds to about 11 beats in five seconds, not 136 beats in the window. The earlier independently calculated estimate was noted as not matching the user's run.

### Frequency selection and audio carrier

**User**

Why avoid encoding very low or very high frequencies? Which of the two files is more suitable for modifying existing audio to carry data?

**Assistant**

Very low and very high frequencies may be inconsistently reproduced by speakers and microphones, attenuated or distorted by the environment, masked by noise, or more strongly absorbed/blocked. A mid-range band is often more reliable. Based on the supplied waveform plots, *CrabRave* was suggested as the more suitable carrier because its relatively high, dense amplitude throughout the segment may mask small modifications better than the quieter tail of *DarudeSandstorm*. The answer noted that suitability also depends on the encoding method.

### User's recording, noise, and SNR

**User**

Interpret the original-versus-recording spectrum, band table, room-noise spectrum, and SNR.

**Assistant**

The assistant explained that speaker response, room acoustics, and the phone microphone affect the recorded frequency balance. Using the user's table, it reported changes of -12.9 dB at 0–250 Hz, +5.7 dB at 250 Hz–2 kHz, -12.1 dB at 2–6 kHz, and +0.3 dB at 6–8 kHz. It described the measured -55.8 dB above 8 kHz as added noise or distortion because the original had no content above that limit.

The user supplied a room-noise tilt of +30.6 dB for 100–500 Hz relative to 4–8 kHz and an SNR of 11.2 dB over 100 Hz–8 kHz. The assistant incorporated those values and explained that the noise was not close to white (which would be approximately flat), and that 11.2 dB corresponds to roughly 13 times the estimated noise power.

## Step 3: Data Encoding in Audio

### LSB, phase modulation, and spread-spectrum noise

**User**

Interpret the time, spectrum, and spectrogram comparisons for LSB encoding, phase modulation, and spread-spectrum noise.

**Assistant**

For LSB, the assistant described the plots as nearly identical to the original because changing least significant sample bits causes only small amplitude changes. For phase modulation, it described the overall waveform, spectrum, and spectrogram as visually similar, since data is carried by phase changes. For spread-spectrum noise, it noted the raised noise-like floor in the frequency spectrum and, after the user clarified the visual observation, added that the encoded spectrogram appeared greener/yellower near 8 kHz, indicating higher magnitude there from added spread-spectrum energy.

### Listening test and decoding results

**User**

The listening-test audio was not audible, the `Audio` widget reported that a sample rate was required, and sometimes the X sample did not appear.

**Assistant**

The assistant explained that notebook audio widgets require playback via their controls and that array input must include its sample rate, e.g. `Audio(a, rate=fa)`. It suggested checking the traceback and noted that clearing notebook output in the listening-test loop can remove or interrupt rendered players; removing `clear_output(wait=True)` can keep controls visible.

**User**

Report blind listening scores: LSB 5/10, PM 4/10, SSN 10/10.

**Assistant**

The assistant formatted the scores and noted that LSB and PM were not reliably distinguishable in this small test, while SSN was consistently distinguishable and had the clearest perceptual effect.

**User**

Report decoding BERs: LSB clean 0.0000, noisy 0.5008; PM clean 0.0000, noisy 0.3815; SSN clean 0.2144, noisy 0.2133.

**Assistant**

The assistant interpreted LSB and PM as perfect in the clean channel, but degraded under noise. LSB at BER 0.5008 was essentially guessing; PM at 0.3815 was better but still error-prone. SSN's BER near 0.214 in both conditions corresponded to about 78.6% of bits correct and was the most robust of these user-provided results.

**User**

Interpret channel-attack results (noise from 40 to 0 dB SNR, MP3 compression, and echo):

| Method | 40 dB | 30 dB | 20 dB | 10 dB | 0 dB | MP3 128k | Echo |
|---|---:|---:|---:|---:|---:|---:|---:|
| LSB | 0.499 | 0.501 | 0.499 | 0.500 | 0.500 | 0.500 | 0.501 |
| PM | 0.196 | 0.371 | 0.461 | 0.493 | 0.502 | 0.505 | 0.203 |
| SSN | 0.215 | 0.217 | 0.220 | 0.240 | 0.317 | 0.233 | 0.260 |

**Assistant**

The assistant identified SSN as the most robust overall in the supplied results, with PM performing comparatively well at 40 dB and under echo but poorly under stronger noise and MP3. LSB remained near chance (BER about 0.5). It explained that SSN distributes energy across the signal, while LSB is vulnerable to sample changes and phase can be disturbed by channel effects. The assistant then recommended LSB for unchanged digital audio, PM when echo resistance was especially relevant, and SSN when resilience to noise/compression outweighed imperceptibility and capacity.

## Step 4: The Mystery Clip and Acoustic Channel

### Mystery codeword

**User**

The user reported variant 6. The decoder's strongest result on the full recording was level 2 ("robust"), codeword `BAT-5397`, confidence 1.79. A second recording beginning about halfway through also decoded `BAT-5397` at level 2 with confidence 0.52; other levels returned corrupted text with lower confidence.

**Assistant**

The assistant formatted the result in a table and explained that the valid, expected-length codeword and its higher confidence identify level 2. Recovery from the second-half recording suggests the message is repeated or distributed through the audio, rather than present only at the beginning.

**User**

At 50 cm, 1 m, and 2 m, the expected codeword no longer decoded. The most likely outputs were corrupted, low-confidence strings: at 50 cm, `········` at level 2 (0.24); at 1 m, `"·C···:A` at level 3 (0.32); at 2 m, `T···~···` at level 5 (0.11).

**Assistant**

The assistant stated that reliable decoding had stopped at the first increased distance tested, 50 cm, and formatted the three most likely outputs and confidence values.

### Testbed setup and distance results

**User**

The user described using a Logitech webcam as the microphone and a phone as the speaker, with a measuring tape for distance. The phone was not visible in the setup photo because it was used to take the photo.

**Assistant**

The assistant polished the setup description and explained the phone's absence from the photo.

**User**

The supplied distance plot showed results at 10, 50, and 100 cm for levels 2 and 4: both levels decoded perfectly at 10 cm; at 50 cm BER was about 0.49/0.48 and character accuracy 0%; at 100 cm BER was about 0.58/0.55 and accuracy approximately 0% (about 2% for level 4).

**Assistant**

The assistant summarized that performance dropped sharply with distance and that neither level reliably recovered the message beyond 10 cm. It reminded the user to submit the notebook-generated `measurements.csv` as raw data.

**User**

The user asked for the main reason for bit errors, the smallest BER, and the maximum distance with correct decoding.

**Assistant**

The assistant attributed errors mainly to weaker received signal relative to room noise and to reflections/distortion. The smallest measured BER was zero at 10 cm for both levels 2 and 4, using the longest message that fit. The maximum tested distance with 100% character accuracy was 10 cm.

**User**

Movement tests: moved 50 cm farther away after 30 seconds in the 10 cm and 50 cm trials, and 50 cm closer after 30 seconds in the 100 cm trial. The provided plot showed approximately 0 BER and 100% accuracy at 10 cm, BER about 0.47 and 5% accuracy at 50 cm, and BER about 0.54 and near-zero accuracy at 100 cm.

**Assistant**

The assistant formatted the results and concluded that movement did not restore reliable decoding at longer distances; distance appeared to remain the dominant limitation in those measurements.

### Own embedded message

**User**

The user reported not hearing a noticeable difference after embedding their matriculation number with level 2.

**Assistant**

The assistant formatted the short answer as: no noticeable difference was audible between the original and encoded audio.

## Step 5: Acoustic Modem

### Detector implementation

**User**

Implement `tone_energies(segment, rate, tones)` and `demodulate(energies)` in `Audio_Modem.ipynb`. The detector should measure the magnitude of the DFT coefficient at each tone; the demodulator should select the strongest tone and return its two bits, most significant bit first.

**Assistant**

The assistant implemented the functions in the notebook:

```python
def tone_energies(segment, rate, tones):
    """Return one DFT magnitude per tone for this symbol."""
    segment = np.asarray(segment, dtype=float).ravel()
    tones = np.asarray(tones, dtype=float).ravel()
    samples = np.arange(segment.size)
    phases = 2 * np.pi * np.outer(tones, samples) / rate
    return np.abs(np.exp(-1j * phases) @ segment)


def demodulate(energies):
    """Convert each strongest tone index into two bits, MSB first."""
    symbols = np.argmax(np.asarray(energies), axis=1)
    bits = np.column_stack((symbols // 2, symbols % 2))
    return bits.astype(np.uint8).ravel()
```

The self-test was run and all three known frames passed:

| Test frame | Result |
|---|---|
| Clean `SELFTEST-123` at 48 kHz | PASS |
| Noisy `Hello WNMC!` at 44.1 kHz | PASS |
| Noisy `21-987-654` with different tones and symbol length at 48 kHz | PASS |

### Recorded modem and data rate

**User**

The received spectrogram showed an up-chirp, a payload of horizontal tone symbols, and a down-chirp. The decoded text was `21-715-917`.

**Assistant**

The assistant described the frame components and reported the decoded text.

**User**

At a symbol length of 17.5 ms, the message no longer decoded. The user asked for the highest working bit rate and its limit.

**Assistant**

The assistant initially stated that the original 35 ms symbols (about 57.1 bit/s) were the highest confirmed rate, and that 17.5 ms (about 114.3 bit/s) failed. It explained that shorter symbols leave less time for tone measurement and increase sensitivity to noise, timing, and recording-channel distortion.

### Modem versus watermark; capacity

**User**

Compare the modem and watermark in audibility, bit rate, robustness, and message-start detection. Recommend one for a museum room-number app and one for marking a radio jingle.

**Assistant**

The assistant contrasted the modem's audible 4-FSK tones, higher bit rate, and chirp-based frame synchronization with the watermark's unobtrusive embedding and lower bit rate. It recommended the modem for a museum app receiving an explicit room number, and the watermark for unobtrusively identifying a radio jingle.

**User**

The user provided a channel bandwidth of 800 Hz, SNR of 11.2 dB, Shannon capacity of 3060.8 bit/s, modem rate of 57.1 bit/s, and level-2 watermark rate of 2.6 bit/s.

**Assistant**

The assistant formatted these values and explained that practical rates are below Shannon capacity because the capacity is theoretical and assumes ideal coding, whereas the modem uses discrete tones, synchronization chirps, and symbol guards, and the watermark prioritizes inaudibility and robustness.

## AI Use Declaration

**User**

Improve the AI-use statement so it accurately describes this chat.

**Assistant**

The assistant suggested:

> I used GitHub Copilot to help draft explanations, interpret results, and implement the modem detector. I reviewed and adapted its suggestions to match my measurements, plots, and notebook outputs, and ran the provided self-tests to check the code. I also reviewed the explanations to understand the reasoning behind them.
