"""The offline embedding model, run for real (skipped when the model has not been downloaded)."""
import os
import unittest

import _testkit  # noqa: F401
from app.config import settings
from app.rag import embedder, local_embedder

MODEL_FILE = os.path.join(local_embedder._model_dir(), "onnx", "model.onnx")


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


@unittest.skipUnless(os.path.exists(MODEL_FILE), "local embedding model not downloaded (see README)")
class LocalEmbedderTests(unittest.TestCase):
    def test_vectors_are_384_numbers_and_unit_length(self):
        vector = local_embedder.embed(["How many leave days do I get?"])[0]
        self.assertEqual(len(vector), 384)
        self.assertAlmostEqual(dot(vector, vector), 1.0, places=4)

    def test_similar_sentences_are_closer_than_unrelated_ones(self):
        question, similar, unrelated = local_embedder.embed([
            "How much notice must a permanent employee give before resigning?",
            "A permanent employee must provide 30 calendar days of written notice.",
            "The cafeteria serves pasta on Fridays.",
        ])
        self.assertGreater(dot(question, similar), dot(question, unrelated) + 0.3)

    def test_a_text_embeds_the_same_alone_or_in_a_batch(self):
        alone = local_embedder.embed(["remote work policy"])[0]
        batched = local_embedder.embed(["a much longer sentence about something else entirely", "remote work policy"])[1]
        self.assertAlmostEqual(dot(alone, batched), 1.0, places=4)         # padding must not change the result

    def test_no_texts_gives_no_vectors(self):
        self.assertEqual(local_embedder.embed([]), [])
        self.assertEqual(embedder.embed_texts([]), [])

    def test_embed_texts_uses_the_local_model_when_configured(self):
        original = settings.embed_provider
        settings.embed_provider = "local"
        try:
            self.assertEqual(len(embedder.embed_texts(["hello"])[0]), 384)
        finally:
            settings.embed_provider = original


class MissingModelTests(unittest.TestCase):
    def test_a_missing_model_folder_gives_a_clear_error(self):
        original_dir, original_session = settings.local_embed_dir, local_embedder._session
        settings.local_embed_dir = os.path.join(os.path.dirname(__file__), "no-such-model-folder")
        local_embedder._session = None
        try:
            with self.assertRaises(RuntimeError) as caught:
                local_embedder.embed(["hello"])
            self.assertIn("not found", str(caught.exception))
            self.assertIn("EMBED_PROVIDER", str(caught.exception))
        finally:
            settings.local_embed_dir, local_embedder._session = original_dir, original_session


if __name__ == "__main__":
    unittest.main()
