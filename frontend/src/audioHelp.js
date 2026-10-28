export const AUDIO_HELP = {
 Gain:{intro:'Gain changes the level entering the EQ and dynamics. It does not edit the recording or change the physical speaker knob.',steps:[
 'Start at 0 dB. Turn playback volume down before trying a boost.',
 'Tap Edit to unlock the knob, then drag upward to increase gain or downward to reduce it. Tap its value for exact entry; use the minus and plus buttons for small steps.',
 'The live meter shows measured chain input/output and an after-gain estimate when Gain is first in the rack. CLIP lights when the gain stage is predicted to reach 0 dBFS; a downstream limiter may still lower the output.',
 'EQ boosts and compressor makeup gain also use headroom. A limiter after them can restrain sample peaks, but cannot repair distortion already in the recording.',
 'Apply settings deliberately. Save a named preset to reuse the complete setup.'],source:'FFmpeg volume filter',url:'https://ffmpeg.org/ffmpeg-filters.html#volume'},
 Equalizer:{intro:'The curve shows the calculated response of the actual filter settings—not microphone data, a spectrum analyzer, or a claim about your room.',steps:[
 'Tap 3-band for Low, Mid and High. Tap 5-band for 125 Hz, 500 Hz, 1 kHz, 4 kHz and 8 kHz.',
 'The shared bands keep their settings. The extra 500 Hz and 4 kHz bands are remembered but do not process audio while 3-band is selected.',
 'Begin with small cuts or boosts. Low changes body and rumble; mid affects the center of the sound; high changes brightness. These are broad bell filters, not instrument-isolation controls.',
 'The host preserves ordinary and high source sample rates; it only upsamples very low-rate files when an active EQ band requires it. Each filter uses Q 0.7; overlapping bands combine in the response curve.'],source:'FFmpeg equalizer filter',url:'https://ffmpeg.org/ffmpeg-filters.html#equalizer'},
 Limiter:{intro:'A final sample-peak limiter reduces peaks above the selected ceiling. It is not a loudspeaker volume limit and is not an oversampled true-peak limiter.',steps:[
 'A cautious trial is a ceiling of -2 dBFS, lookahead of 5 ms and release of 100 ms. This is a starting point, not a universal mastering target.',
 'Attack / lookahead delays the signal to anticipate a peak. The engine supports 0.1–80 ms; increasing it changes latency and how the peak is shaped.',
 'Release controls the return to normal gain. If the sound crackles or pulses, reduce the amount of limiting and try a longer release. Listen to the loudest sections.',
 'Automatic output leveling is disabled, so the selected ceiling is not immediately boosted back to 0 dBFS. Other system volume stages and Bluetooth encoding remain outside this limiter.',
 'Bypass only this effect to compare, at a low playback volume. Distortion already in the source cannot be undone.'],source:'FFmpeg alimiter',url:'https://ffmpeg.org/ffmpeg-filters.html#alimiter'},
 Compressor:{intro:'Downward compression reduces portions above the threshold. It does not automatically raise quiet parts; makeup gain is a separate control.',steps:[
 'Start with makeup gain at 0 dB, ratio about 2:1, attack 20 ms and release 250 ms. Begin with a high threshold, then lower it while listening to loud sections. A fixed -20 dBFS threshold may do little on one file and too much on another.',
 'Ratio controls reduction above the threshold: at 2:1, a 6 dB input rise above threshold becomes roughly 3 dB at the output away from the soft knee.',
 'Faster attack reduces more of the beginning of a sound; slower attack preserves more transient detail. Very short release can sound rough; very long release may keep the recording ducked.',
 'Add makeup gain only to compensate for the level reduction. Compare bypassed and processed audio at similar listening loudness; louder is not necessarily better.',
 'Master Glue uses documented SSL timing/ratio settings. BlueMAX-inspired presets reuse published ratios/timings but adapt digital thresholds; none is a hardware emulation or a preset auditioned on your speakers.'],source:'PreSonus dynamics guide and published starting presets',url:'https://www.presonus.com/blogs/technical/how-to-use-dynamics-processing-getting-started-with-compressors-gates-and-more'},
};
