"""app/rag/embedder.py: the API embedding path (batching, the per-minute allowance, retries) and dispatch."""
import unittest
from types import SimpleNamespace
from unittest import mock

import httpx
from openai import RateLimitError

import _testkit  # noqa: F401
from app.config import settings
from app.rag import embedder


def rate_limit_error():
    request = httpx.Request("POST", "http://test.invalid/embeddings")
    return RateLimitError("slow down", response=httpx.Response(429, request=request), body=None)


class ApiEmbedderTests(unittest.TestCase):
    def setUp(self):
        self.batches, self.sleeps, self.failures = [], [], []
        self.clock = {"now": 100.0}

        def create(model, input):
            if self.failures:
                raise self.failures.pop(0)
            self.batches.append(list(input))
            return SimpleNamespace(data=[SimpleNamespace(embedding=[float(len(text)), 1.0]) for text in input])

        def fake_sleep(seconds):
            self.sleeps.append(seconds)
            self.clock["now"] += seconds

        client = SimpleNamespace(embeddings=SimpleNamespace(create=create))
        for patcher in (mock.patch.object(embedder, "_get_client", return_value=client),
                        mock.patch.object(embedder.time, "sleep", fake_sleep),
                        mock.patch.object(embedder.time, "monotonic", lambda: self.clock["now"]),
                        mock.patch.object(settings, "embed_provider", "openai"),
                        mock.patch.object(settings, "embed_rpm", 0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_without_a_limit_texts_go_in_batches_of_ten_in_order(self):
        texts = [f"text {i:02d}" for i in range(25)]
        vectors = embedder.embed_texts(texts)
        self.assertEqual([len(batch) for batch in self.batches], [10, 10, 5])
        self.assertEqual([batch for group in self.batches for batch in group], texts)       # nothing lost or reordered
        self.assertEqual([v[0] for v in vectors], [float(len(t)) for t in texts])
        self.assertEqual(self.sleeps, [])

    def test_a_batch_never_exceeds_the_per_minute_allowance(self):
        with mock.patch.object(settings, "embed_rpm", 4):
            embedder.embed_texts([f"t{i}" for i in range(10)])
        self.assertTrue(all(len(batch) <= 4 for batch in self.batches))
        self.assertEqual([len(b) for b in self.batches], [4, 4, 2])
        self.assertEqual(len(self.sleeps), 2)                    # it waited out the minute twice rather than overshooting
        self.assertTrue(all(wait > 50 for wait in self.sleeps))

    def test_a_rate_limit_error_is_retried_after_a_wait(self):
        self.failures = [rate_limit_error()]
        vectors = embedder.embed_texts(["only text"])
        self.assertEqual(len(vectors), 1)
        self.assertEqual(self.sleeps, [30])

    def test_it_gives_up_after_five_attempts_and_raises_the_rate_limit_error(self):
        self.failures = [rate_limit_error() for _ in range(5)]
        with self.assertRaises(RateLimitError):
            embedder.embed_texts(["only text"])
        self.assertEqual(self.sleeps, [30, 60, 90, 120])         # growing waits between the five attempts

    def test_no_texts_means_no_call(self):
        self.assertEqual(embedder.embed_texts([]), [])
        self.assertEqual(self.batches, [])

    def test_the_local_provider_never_touches_the_api(self):
        with mock.patch.object(settings, "embed_provider", "local"), \
                mock.patch("app.rag.local_embedder.embed", return_value=[[0.5, 0.5]]) as local:
            self.assertEqual(embedder.embed_texts(["hello"]), [[0.5, 0.5]])
        local.assert_called_once_with(["hello"])
        self.assertEqual(self.batches, [])


if __name__ == "__main__":
    unittest.main()
