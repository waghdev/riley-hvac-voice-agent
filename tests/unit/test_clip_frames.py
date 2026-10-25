from agent.clips import Clip
from agent.main import clip_frames


async def test_clip_is_cut_into_20ms_frames_covering_every_sample():
    rate = 24000
    pcm = bytes(range(256)) * 100  # 25,600 bytes = 12,800 samples, not a whole number of frames
    frames = [f async for f in clip_frames(Clip(pcm=pcm, sample_rate=rate))]

    assert all(f.samples_per_channel == rate // 50 for f in frames)  # 480 samples = 20 ms
    assert all(f.sample_rate == rate and f.num_channels == 1 for f in frames)
    played = b"".join(bytes(f.data.cast("B")) for f in frames)
    assert played[: len(pcm)] == pcm  # nothing lost or reordered
    assert set(played[len(pcm) :]) <= {0}  # only the last frame is padded, with silence
    assert len(frames) == -(-len(pcm) // (480 * 2))  # ceiling division
