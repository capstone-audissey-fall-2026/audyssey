import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from audyssey.contracts import SourcePlan, Span
from audyssey.media import read_wav, write_wav
from audyssey.tools.separation import real
from tests.sam_audio_fakes import Tensor, fake_runtime


class SamSeparationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.mono = write_wav(self.root / 'mono.wav', np.ones((100, 1)))
        self.plan = SourcePlan(name='voice', kind='dialogue', description='a voice')
        self.torch, self.sam, self.model, self.processor, self.batch = fake_runtime(
            'SAMAudio', 'SAMAudioProcessor'
        )
        self.model.separate.return_value = SimpleNamespace(target=[Tensor(np.full((1, 100), 0.5))])
        env = patch.dict(os.environ, {'AUDYSSEY_SAM_AUDIO_DEVICE': 'cpu'}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        modules = patch.dict(sys.modules, torch=self.torch, sam_audio=self.sam)
        modules.start()
        self.addCleanup(modules.stop)
        if hasattr(real, '_load'):
            real._load.cache_clear()
            self.addCleanup(real._load.cache_clear)

    def separate(self, attempt=1, video=None):
        return real.separate(self.mono, self.plan, video, self.root / 'track.wav', attempt)

    def test_separate_passes_description_and_span_anchors(self):
        self.plan.spans = [Span(start=0, end=0.001), Span(start=0.001, end=0.002)]
        self.separate()
        args = self.processor.call_args.kwargs
        self.assertEqual(args['descriptions'], ['a voice'])
        self.assertEqual(args['anchors'], [[['+', 0.0, 0.001], ['+', 0.001, 0.002]]])
        self.assertNotIn('masked_videos', args)
        np.testing.assert_array_equal(args['audios'][0].data, np.ones((1, 100)))
        self.batch.to.assert_called_once_with('cpu')
        self.model.separate.assert_called_once_with(self.batch, reranking_candidates=1, predict_spans=False)
        np.testing.assert_array_equal(read_wav(self.root / 'track.wav'), np.full((100, 1), 0.5))

    def test_separate_without_spans_uses_no_anchors(self):
        with patch.dict(os.environ, AUDYSSEY_SAM_AUDIO_PREDICT_SPANS='true', AUDYSSEY_SAM_AUDIO_RERANKING_CANDIDATES='3'):
            self.separate()
        self.assertIsNone(self.processor.call_args.kwargs['anchors'])
        self.model.separate.assert_called_once_with(self.batch, reranking_candidates=3, predict_spans=True)

    def test_separate_writes_same_length_mono_48k(self):
        for length in (80, 120):
            with self.subTest(length=length):
                self.model.separate.return_value = SimpleNamespace(target=[Tensor(np.full((1, length), 0.5))])
                rate, data = wavfile.read(self.separate())
                self.assertEqual(rate, 48000)
                self.assertEqual(data.shape, (100,))
                self.assertEqual(read_wav(self.root / "track.wav").shape, (100, 1))
                self.assertEqual(data.dtype, np.float32)
                np.testing.assert_array_equal(data[:min(length, 100)], 0.5)
                if length < 100:
                    np.testing.assert_array_equal(data[length:], 0)

    def test_attempt_sets_seed(self):
        self.separate(1)
        self.separate(2)
        self.assertEqual([c.args[0] for c in self.torch.manual_seed.call_args_list], [1, 2])

    def test_model_loaded_once(self):
        self.separate()
        self.separate()
        self.sam.SAMAudio.from_pretrained.assert_called_once()
        self.sam.SAMAudioProcessor.from_pretrained.assert_called_once_with('facebook/sam-audio-large-tv')
        self.model.to.assert_called_once_with('cpu')
        self.model.eval.assert_called_once_with()

    def test_unused_rankers_and_span_predictor_never_built(self):
        # SAMAudio builds its rankers (incl. the official Judge) in __init__, so they
        # must be disabled through config overrides, not removed after loading.
        self.separate()
        self.sam.SAMAudio.from_pretrained.assert_called_once_with(
            'facebook/sam-audio-large-tv', visual_ranker=None, text_ranker=None, span_predictor=None
        )

    def test_reranking_builds_rankers_from_our_settings(self):
        # With several candidates SAMAudio needs its rankers; point the Judge ranker at our
        # configured Judge (official or mirror) instead of the hardcoded official repo.
        with patch.dict(os.environ, AUDYSSEY_SAM_AUDIO_PREDICT_SPANS='true', AUDYSSEY_SAM_AUDIO_RERANKING_CANDIDATES='3'):
            self.separate()
        self.sam.SAMAudio.from_pretrained.assert_called_once_with(
            'facebook/sam-audio-large-tv',
            text_ranker={'kind': 'ensemble', 'rankers': {
                'clap': [{'kind': 'clap', 'checkpoint': None}, 5.0],
                'judge': [{'kind': 'judge', 'checkpoint_or_model_id': 'facebook/sam-audio-judge'}, 1.0],
            }},
            visual_ranker=None,
        )

    def test_reranking_uses_configured_checkpoints(self):
        env = {
            'AUDYSSEY_SAM_AUDIO_RERANKING_CANDIDATES': '4',
            'AUDYSSEY_SAM_AUDIO_JUDGE_MODEL': 'mrfakename/sam-audio-judge',
            'AUDYSSEY_SAM_AUDIO_CLAP_CHECKPOINT': '/ckpt/630k-best.pt',
            'AUDYSSEY_SAM_AUDIO_IMAGEBIND_CHECKPOINT': '/ckpt/imagebind_huge.pth',
        }
        with patch.dict(os.environ, env):
            self.separate()
        kwargs = self.sam.SAMAudio.from_pretrained.call_args.kwargs
        self.assertEqual(kwargs['text_ranker']['rankers']['clap'][0]['checkpoint'], '/ckpt/630k-best.pt')
        self.assertEqual(kwargs['text_ranker']['rankers']['judge'][0]['checkpoint_or_model_id'], 'mrfakename/sam-audio-judge')
        self.assertEqual(kwargs['visual_ranker'], {'kind': 'imagebind', 'checkpoint': '/ckpt/imagebind_huge.pth'})
        self.assertIsNone(kwargs['span_predictor'])
        self.model.separate.assert_called_once_with(self.batch, reranking_candidates=4, predict_spans=False)

    def test_missing_gpu_env_message(self):
        with patch.dict(sys.modules, torch=None, sam_audio=None):
            with self.assertRaisesRegex(RuntimeError, 'SAM Audio is not installed: install the gpu/ environment'):
                self.separate()

    def test_real_separate_passes_masked_video_only_when_given(self):
        from audyssey.contracts import VisualHint
        self.plan.visual_hint = VisualHint(time=0, box=(0, 0, .5, 1), description='a')
        self.separate()
        self.assertNotIn('masked_videos', self.processor.call_args.kwargs)
        self.separate(video=Path('unused.mp4'))
        self.assertEqual(self.processor.call_args.kwargs['masked_videos'], ['unused.mp4'])

    def test_source_batch_uses_entire_audio_and_preserves_anchors(self):
        self.plan.spans = [Span(start=0.0001, end=0.0005)]
        other = SourcePlan(name="wind", kind="ambience", description="rushing wind")
        outs = [self.root / "voice.wav", self.root / "wind.wav"]
        self.model.separate.return_value = SimpleNamespace(
            target=[Tensor(np.ones(100)), Tensor(np.full(100, 2))]
        )
        with patch.dict(os.environ, AUDYSSEY_SAM_AUDIO_BATCH_SIZE="32"):
            self.assertEqual(real.separate_batch(self.mono, [self.plan, other], outs, 1), outs)
        args = self.processor.call_args.kwargs
        self.assertEqual(args["descriptions"], ["a voice", "rushing wind"])
        self.assertEqual(args["anchors"], [[["+", 0.0001, 0.0005]], []])
        for audio in args["audios"]:
            np.testing.assert_array_equal(audio.data, np.ones((1, 100)))
        np.testing.assert_array_equal(read_wav(outs[0]), 1)
        np.testing.assert_array_equal(read_wav(outs[1]), 2)

    def test_explicit_anchors_do_not_disable_span_prediction_for_other_sources(self):
        self.plan.spans = [Span(start=0.0001, end=0.0005)]
        other = SourcePlan(name="wind", kind="ambience", description="rushing wind")
        self.model.separate.return_value = SimpleNamespace(target=[Tensor(np.ones(100))])
        with patch.dict(os.environ, AUDYSSEY_SAM_AUDIO_BATCH_SIZE="4",
                        AUDYSSEY_SAM_AUDIO_PREDICT_SPANS="true"):
            real.separate_batch(
                self.mono, [self.plan, other], [self.root / "a.wav", self.root / "b.wav"], 1
            )
        self.assertEqual([c.kwargs["anchors"] for c in self.processor.call_args_list],
                         [[[["+", 0.0001, 0.0005]]], None])
        self.assertTrue(all(c.kwargs["predict_spans"] for c in self.model.separate.call_args_list))

    def test_cuda_oom_keeps_lower_batch_size_and_restores_float32_precision(self):
        from unittest.mock import Mock

        class OutOfMemoryError(RuntimeError):
            pass

        self.torch.cuda = SimpleNamespace(OutOfMemoryError=OutOfMemoryError, empty_cache=Mock())
        self.torch.get_float32_matmul_precision = Mock(return_value="highest")
        self.torch.set_float32_matmul_precision = Mock()
        calls = []
        plans = [self.plan.model_copy(update={"description": str(i)}) for i in range(32)]
        outs = [self.root / f"{i}.wav" for i in range(len(plans))]

        def infer(*args, **kwargs):
            descriptions = self.processor.call_args.kwargs["descriptions"]
            calls.append(len(descriptions))
            if len(descriptions) > 8:
                raise OutOfMemoryError()
            return SimpleNamespace(target=[Tensor(np.full(100, int(s))) for s in descriptions])

        self.model.separate.side_effect = infer
        with patch.dict(os.environ, AUDYSSEY_SAM_AUDIO_BATCH_SIZE="32",
                        AUDYSSEY_SAM_AUDIO_DEVICE="cuda", AUDYSSEY_SAM_AUDIO_ALLOW_TF32="true"):
            real.separate_batch(self.mono, plans, outs, 1)
        self.assertEqual(calls, [32, 16, 8, 8, 8, 8])
        self.assertEqual(self.torch.cuda.empty_cache.call_count, 2)
        precision_calls = self.torch.set_float32_matmul_precision.call_args_list
        self.assertEqual([c.args[0] for c in precision_calls], ["high", "highest"] * 6)
        for i, out in enumerate(outs):
            np.testing.assert_array_equal(read_wav(out), i)
