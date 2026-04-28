# Security and Privacy

## Default

Default bind address:

```text
127.0.0.1
```

## LAN Mode

If using from another computer:

1. set `LOCAL_ASR_HOST=0.0.0.0`;
2. set `LOCAL_ASR_API_KEY`;
3. restrict firewall to trusted local IPs;
4. never expose to the public internet.

## Sensitive Data

The service processes meeting audio and transcripts. Treat all content as sensitive.

## MVP Rules

- no audio saved by default;
- no transcripts saved by default;
- no raw transcript logs by default;
- `.env` is ignored;
- debug transcript logging must be explicit.
