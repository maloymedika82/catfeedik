from backend.fingerprint import FRAME_BYTES,frame_hash,similar


def test_video_signature_matches_small_visual_changes_only():
    pixels=bytes([value for _ in range(8) for value in range(9)])
    assert len(pixels)==FRAME_BYTES
    signature=frame_hash(pixels)
    assert isinstance(signature,int) and signature.bit_length()<=64
    first=[f'{value:016x}' for value in (signature,signature^0b11,signature^0b101010)]
    edited=[f'{value:016x}' for value in (signature^1,signature^0b1,signature^0b101011)]
    assert similar(first,edited)
    assert not similar(first,['ffffffffffffffff']*3)
    assert not similar(first,['invalid']*3)
