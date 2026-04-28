from local_asr_service.schemas import TranscriptSegment


def test_transcript_segment_schema() -> None:
    seg = TranscriptSegment(id="1", text="hello")
    assert seg.text == "hello"
    assert seg.status == "final"
