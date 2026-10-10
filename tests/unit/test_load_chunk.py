"""Stages 1 and 2: loading documents (including a real PDF) and chunking them."""
import contextlib
import io
import logging
import os
import tempfile
import unittest

import _testkit  # noqa: F401  (puts the project on sys.path)
from app.rag import chunker, loader


def minimal_pdf(text):
    """A tiny but valid one-page PDF whose text layer says `text`, built by hand."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_at)
    return out


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.dir = self.enterContext(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))

    def write(self, relative, content, mode="w"):
        path = os.path.join(self.dir, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        kwargs = {} if "b" in mode else {"encoding": "utf-8"}
        with open(path, mode, **kwargs) as handle:
            handle.write(content)

    def test_reads_markdown_and_text_including_sub_folders(self):
        self.write("a.md", "# Leave\n18 days")
        self.write("sub/b.txt", "notice is 30 days")
        docs = loader.load_documents(self.dir)
        self.assertEqual([d["source"] for d in docs], ["a.md", "sub/b.txt"])     # forward slashes, sorted
        self.assertIn("18 days", docs[0]["text"])

    def test_skips_unsupported_empty_and_unreadable_files(self):
        self.write("keep.md", "real text")
        self.write("data.json", "{}")
        self.write("blank.md", "   \n\n")
        self.write("broken.pdf", b"this is not a pdf", mode="wb")
        logging.getLogger("pypdf").setLevel(logging.CRITICAL)      # the broken PDF is expected to complain
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            sources = [d["source"] for d in loader.load_documents(self.dir)]
        self.assertEqual(sources, ["keep.md"])
        self.assertIn("skipped broken.pdf", printed.getvalue())    # and the loader says what it skipped

    def test_a_stray_non_utf8_byte_does_not_crash_the_load(self):
        self.write("odd.md", b"caf\xe9 policy applies", mode="wb")
        docs = loader.load_documents(self.dir)
        self.assertEqual(len(docs), 1)
        self.assertIn("policy applies", docs[0]["text"])

    def test_a_real_pdf_is_read(self):
        self.write("handbook.pdf", minimal_pdf("Hello PDF policy"), mode="wb")
        docs = loader.load_documents(self.dir)
        self.assertEqual([d["source"] for d in docs], ["handbook.pdf"])
        self.assertIn("Hello PDF policy", docs[0]["text"])

    def test_an_empty_folder_gives_no_documents(self):
        self.assertEqual(loader.load_documents(self.dir), [])


class ChunkerTests(unittest.TestCase):
    DOC = [{"source": "leave.md", "text": ("Paragraph about annual leave rules. " * 6 + "\n\n") * 12}]

    def test_overlap_not_smaller_than_size_is_rejected(self):
        with self.assertRaises(ValueError):
            chunker.chunk_documents(self.DOC, 100, 100)
        with self.assertRaises(ValueError):
            chunker.chunk_documents(self.DOC, 100, 150)

    def test_no_chunk_exceeds_the_size_and_none_is_empty(self):
        chunks = chunker.chunk_documents(self.DOC, 300, 50)
        self.assertGreater(len(chunks), 3)
        for item in chunks:
            self.assertLessEqual(len(item["text"]), 300)
            self.assertTrue(item["text"].strip())

    def test_each_chunk_remembers_its_source_and_has_a_unique_id(self):
        chunks = chunker.chunk_documents(self.DOC, 300, 50)
        self.assertEqual({c["source"] for c in chunks}, {"leave.md"})
        ids = [c["chunk_id"] for c in chunks]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(i.startswith("leave.md#") for i in ids))

    def test_smaller_chunks_mean_more_of_them(self):
        small = chunker.chunk_documents(self.DOC, 200, 20)
        large = chunker.chunk_documents(self.DOC, 800, 20)
        self.assertGreater(len(small), len(large))

    def test_a_short_document_is_one_chunk_and_blank_is_none(self):
        self.assertEqual(len(chunker.chunk_documents([{"source": "s.md", "text": "tiny"}], 800, 120)), 1)
        self.assertEqual(chunker.chunk_documents([{"source": "s.md", "text": "   "}], 800, 120), [])
        self.assertEqual(chunker.chunk_documents([], 800, 120), [])


if __name__ == "__main__":
    unittest.main()
