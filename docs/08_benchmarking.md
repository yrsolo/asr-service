# Benchmarking

## Goal

Find best ASR profile for GTX 1080 Ti.

## Test Files

Prepare samples:

- clean Russian speech;
- noisy Russian meeting;
- English technical speech;
- mixed Russian/English;
- microphone recording;
- system audio recording.

## Command

```bash
python scripts/benchmark_models.py samples/test_ru.wav --models fw-small-int8,fw-medium-int8-fp16,fw-large-v3-turbo-int8-fp16 --language ru
```

## Metrics

- processing seconds;
- audio duration;
- real-time factor;
- text length;
- qualitative quality notes.

## Output Example

```json
{
  "audio_file": "samples/test_ru.wav",
  "results": [
    {
      "model_id": "fw-medium-int8-fp16",
      "processing_sec": 18.4,
      "duration_sec": 60.0,
      "rtf": 0.31
    }
  ]
}
```
